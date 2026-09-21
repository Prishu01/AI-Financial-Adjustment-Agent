"""
AI Financial Adjustment Agent — CLI entry point.

Usage
-----
    python -m app.main                          # uses data/ and output/
    python -m app.main --data-dir data --output-dir output
    python -m app.main --verbose

The script:
  1. Loads .env (if present) for LLM_PROVIDER / API keys.
  2. Runs the AdjustmentAgent pipeline.
  3. Prints a Rich summary table to the terminal.
  4. Exits 0 on success, 1 on unhandled error.

Input files are NEVER modified.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

# Force UTF-8 on Windows consoles that default to cp1252
import sys as _sys
if _sys.platform == "win32":
    import io as _io
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
    _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding="utf-8", errors="replace")

from app.agents.adjustment_agent import AdjustmentAgent  # noqa: E402
from app.models.schemas import BatchResult, EntryStatus  # noqa: E402

console = Console()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AI Financial Adjustment Agent — validates manual journal entries.",
    )
    p.add_argument("--data-dir", default="data", help="Input data directory (default: data/)")
    p.add_argument("--output-dir", default="output", help="Output directory (default: output/)")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return p.parse_args()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(name)-28s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Rich display helpers
# ---------------------------------------------------------------------------

_STATUS_STYLE = {
    EntryStatus.ACCEPT: "green",
    EntryStatus.REJECT: "bold red",
    EntryStatus.QUARANTINE: "yellow",
}


def _print_results_table(batch: BatchResult) -> None:
    table = Table(
        title=f"Adjustment Validation Results — {batch.period}",
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Description", width=38)
    table.add_column("Status", width=12)
    table.add_column("Debit", justify="right", width=14)
    table.add_column("Credit", justify="right", width=14)
    table.add_column("Diff", justify="right", width=10)
    table.add_column("Err", justify="right", width=5)
    table.add_column("Warn", justify="right", width=5)

    for r in batch.results:
        style = _STATUS_STYLE.get(r.status, "white")
        desc = r.description[:37] + "…" if len(r.description) > 38 else r.description
        table.add_row(
            r.entry_id,
            desc,
            f"[{style}]{r.status.value}[/{style}]",
            f"{float(r.total_debit):,.2f}",
            f"{float(r.total_credit):,.2f}",
            f"[{'red' if r.difference else 'green'}]{float(r.difference):,.2f}[/{'red' if r.difference else 'green'}]",
            str(r.error_count) if r.error_count else "",
            str(r.warning_count) if r.warning_count else "",
        )

    console.print(table)


def _print_summary_panel(batch: BatchResult) -> None:
    accepted = len(batch.accepted)
    rejected = len(batch.rejected)
    quarantined = len(batch.quarantined)

    body = (
        f"  Period              : {batch.period}\n"
        f"  Functional currency : {batch.functional_currency}\n"
        f"\n"
        f"  Total entries       : {batch.total_entries}\n"
        f"  [green]Accepted[/green]            : {accepted}\n"
        f"  [red]Rejected[/red]            : {rejected}\n"
        f"  [yellow]Quarantined[/yellow]         : {quarantined}\n"
        f"\n"
        f"  Total errors        : {batch.total_errors}\n"
        f"  Total warnings      : {batch.total_warnings}\n"
    )

    if batch.quarantined:
        body += "\n  [yellow]Quarantined entries require human review before posting.[/yellow]\n"

    console.print(Panel(body, title="✅ Pipeline Complete", border_style="green"))


def _print_quarantine_detail(batch: BatchResult) -> None:
    if not batch.quarantined:
        return
    console.print("\n[bold yellow]─── Quarantine Detail ───[/bold yellow]")
    for r in batch.quarantined:
        console.print(f"\n  [yellow]▶ {r.entry_id}[/yellow]  {r.description}")
        console.print(f"    Source : {r.source}")
        for w in r.warnings:
            console.print(f"    [yellow]⚠[/yellow]  {w}")
        if r.review_reason:
            # show first 2 lines of review_reason only
            first_lines = r.review_reason.split("\n")[:3]
            for line in first_lines:
                console.print(f"    [dim]{line}[/dim]")


def _print_reject_detail(batch: BatchResult) -> None:
    if not batch.rejected:
        return
    console.print("\n[bold red]─── Reject Detail ───[/bold red]")
    for r in batch.rejected:
        console.print(f"\n  [red]✗ {r.entry_id}[/red]  {r.description}")
        for e in r.errors:
            console.print(f"    [red]✗[/red]  {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    _setup_logging(args.verbose)

    console.print()
    console.print(Panel(
        "[bold cyan]AI Financial Adjustment Agent[/bold cyan]",
        subtitle="Manual Journal Entry Validator",
        border_style="cyan",
    ))
    console.print()

    agent = AdjustmentAgent(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
    )

    try:
        batch = agent.run()
    except FileNotFoundError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
        logging.exception("Pipeline failed")
        sys.exit(1)

    _print_results_table(batch)
    _print_reject_detail(batch)
    _print_quarantine_detail(batch)
    _print_summary_panel(batch)

    console.print(
        f"\n  Output files in [cyan]{args.output_dir}/[/cyan]\n"
        "    • adjustment_results.json\n"
        "    • adjustment_summary.csv\n"
    )


if __name__ == "__main__":
    main()
