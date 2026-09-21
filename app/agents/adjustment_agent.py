"""
Adjustment Agent — top-level orchestrator.

Wires together:
  1. CoAService          — loads chart_of_accounts.csv
  2. AdjustmentService   — loads manual_adjustments.json, runs all validators
  3. LLMProvider         — optional LLM for plain-English explanations
  4. ExplanationAgent    — builds the explanation callable
  5. OutputWriter        — writes adjustment_results.json + adjustment_summary.csv

This is the single public entry-point called by main.py and the Streamlit app.
It returns a BatchResult so callers can render the data however they need.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.agents.explanation_agent import build_explanation_fn
from app.agents.llm_provider import LLMProvider
from app.models.schemas import BatchResult
from app.services.adjustment_service import AdjustmentService
from app.services.coa_service import CoAService
from app.utils.output_writer import write_outputs

logger = logging.getLogger(__name__)


class AdjustmentAgent:
    """
    Orchestrates the full manual-adjustments validation pipeline.

    Parameters
    ----------
    data_dir  : path to the directory that contains the input CSV/JSON files
    output_dir: path to write output files into
    """

    def __init__(
        self,
        data_dir: str | Path = "data",
        output_dir: str | Path = "output",
    ) -> None:
        self._data_dir = Path(data_dir)
        self._output_dir = Path(output_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> BatchResult:
        """
        Execute the full pipeline and return the BatchResult.

        Side-effects
        ------------
        Writes output/adjustment_results.json and output/adjustment_summary.csv.
        Input files are never modified.
        """
        logger.info("=== AdjustmentAgent: pipeline start ===")

        # 1. Load Chart of Accounts
        coa_path = self._data_dir / "chart_of_accounts.csv"
        coa = CoAService(coa_path)
        logger.info("CoA loaded: %d accounts", len(coa.all_accounts))

        # 2. Build LLM provider (may be "none" — always safe)
        provider = LLMProvider.from_env()
        if provider.is_available:
            logger.info("LLM provider active (%s)", provider._provider)
        else:
            logger.info(
                "LLM provider not configured — using deterministic explanations"
            )

        # 3. Build explanation callable
        explanation_fn = build_explanation_fn(provider)

        # 4. Run adjustment service (validation + decisions)
        service = AdjustmentService(coa=coa, data_dir=self._data_dir)
        batch = service.process_batch(explanation_fn=explanation_fn)

        logger.info(
            "Batch complete: total=%d  accept=%d  reject=%d  quarantine=%d",
            batch.total_entries,
            len(batch.accepted),
            len(batch.rejected),
            len(batch.quarantined),
        )

        # 5. Write outputs
        write_outputs(batch, self._output_dir)
        logger.info("Outputs written to %s", self._output_dir)
        logger.info("=== AdjustmentAgent: pipeline done ===")

        return batch
