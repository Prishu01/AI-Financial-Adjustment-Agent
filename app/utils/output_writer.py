"""
Output Writer.

Writes the two required output artefacts from a BatchResult:

  output/adjustment_results.json   — one record per journal entry
  output/adjustment_summary.csv    — flat tabular summary

Design rules:
  - Never modifies input files.
  - Idempotent: running twice with the same input overwrites identically.
  - Uses json.dumps with sort_keys=False to preserve field order.
  - CSV uses pandas to guarantee consistent quoting.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

import pandas as pd

from app.models.schemas import BatchResult, EntryResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def write_outputs(batch: BatchResult, output_dir: str | Path) -> dict[str, Path]:
    """
    Write both output files and return a dict of {name: path}.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "adjustment_results.json"
    csv_path = out / "adjustment_summary.csv"

    _write_json(batch, json_path)
    _write_csv(batch, csv_path)

    logger.info("Wrote %s", json_path)
    logger.info("Wrote %s", csv_path)

    return {"adjustment_results": json_path, "adjustment_summary": csv_path}


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def _write_json(batch: BatchResult, path: Path) -> None:
    records = [_result_to_dict(r) for r in batch.results]
    payload = {
        "period": batch.period,
        "functional_currency": batch.functional_currency,
        "generated_at": batch.generated_at.isoformat(),
        "summary": {
            "total": batch.total_entries,
            "accepted": len(batch.accepted),
            "rejected": len(batch.rejected),
            "quarantined": len(batch.quarantined),
            "total_errors": batch.total_errors,
            "total_warnings": batch.total_warnings,
        },
        "results": records,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=_json_default)


def _result_to_dict(r: EntryResult) -> dict:
    return {
        "entry_id": r.entry_id,
        "status": r.status.value,
        "description": r.description,
        "date": r.date,
        "source": r.source,
        "total_debit": float(r.total_debit),
        "total_credit": float(r.total_credit),
        "difference": float(r.difference),
        "errors": r.errors,
        "warnings": r.warnings,
        "account_checks": [
            {
                "account": c.account,
                "exists_in_coa": c.exists_in_coa,
                "is_postable": c.is_postable,
                "account_type": c.account_type,
                "normal_balance": c.normal_balance,
                "issue": c.issue,
            }
            for c in r.account_checks
        ],
        "explanation": r.explanation,
        "human_review_required": r.human_review_required,
        "review_reason": r.review_reason,
        "original_lines": [
            {
                "account": line.account,
                "debit": float(line.debit),
                "credit": float(line.credit),
                "memo": line.memo,
            }
            for line in r.original_lines
        ],
    }


def _json_default(obj: object) -> object:
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def _write_csv(batch: BatchResult, path: Path) -> None:
    rows = [r.to_summary_row() for r in batch.results]
    df = pd.DataFrame(rows, columns=[
        "entry_id",
        "status",
        "total_debit",
        "total_credit",
        "difference",
        "error_count",
        "warning_count",
        "human_review_required",
        "explanation",
    ])
    df.to_csv(path, index=False)
