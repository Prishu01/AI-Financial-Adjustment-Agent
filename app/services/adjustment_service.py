"""
Adjustment Service.

Orchestrates the full validation pipeline for a batch of manual adjustments:

  1. Load manual_adjustments.json  → list[RawJournalEntry]
  2. For each entry, run every deterministic validator
  3. Collect all issues, compute totals, decide status
  4. Attach LLM explanation (or deterministic fallback)
  5. Return BatchResult

Decision rules (deterministic, no LLM overrides):
  REJECT     → any ERROR-severity issue
  QUARANTINE → no ERRORs but ≥1 WARNING
  ACCEPT     → zero issues

The service never modifies or re-writes the source JSON.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Optional

from app.models.schemas import (
    AccountCheck,
    BatchResult,
    EntryResult,
    EntryStatus,
    IssueSeverity,
    RawJournalEntry,
    ValidationIssue,
)
from app.services.coa_service import CoAService
from app.validators.account_validator import validate_accounts
from app.validators.balance_validator import compute_totals, validate_balance
from app.validators.duplicate_validator import validate_duplicates
from app.validators.field_validator import validate_required_fields
from app.validators.intercompany_validator import validate_intercompany
from app.validators.semantic_validator import validate_semantics

logger = logging.getLogger(__name__)


class AdjustmentService:
    """
    Loads manual adjustments, runs all validators, produces EntryResult objects.
    """

    def __init__(self, coa: CoAService, data_dir: str | Path = "data") -> None:
        self._coa = coa
        self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def process_batch(
        self,
        explanation_fn: Optional[callable] = None,
    ) -> BatchResult:
        """
        Load manual_adjustments.json, validate every entry, return BatchResult.

        Parameters
        ----------
        explanation_fn : optional callable
            If provided, called as explanation_fn(entry, issues) → str.
            Falls back to deterministic text when None or when the call fails.
        """
        path = self._data_dir / "manual_adjustments.json"
        raw_data = self._load_json(path)

        period = raw_data.get("period", "unknown")
        functional_currency = raw_data.get("functional_currency", "USD")
        raw_entries: list[dict] = raw_data.get("entries", [])

        logger.info(
            "Processing batch: period=%s, functional_currency=%s, entries=%d",
            period, functional_currency, len(raw_entries),
        )

        results: list[EntryResult] = []
        for raw in raw_entries:
            result = self._process_entry(raw, explanation_fn)
            results.append(result)
            logger.debug(
                "  %s → %s  (errors=%d, warnings=%d)",
                result.entry_id, result.status.value,
                result.error_count, result.warning_count,
            )

        return BatchResult(
            period=period,
            functional_currency=functional_currency,
            results=results,
        )

    # ------------------------------------------------------------------
    # Per-entry processing
    # ------------------------------------------------------------------

    def _process_entry(
        self,
        raw: dict,
        explanation_fn: Optional[callable],
    ) -> EntryResult:
        """Run all validators on one raw journal entry dict."""
        all_issues: list[ValidationIssue] = []
        account_checks: list[AccountCheck] = []

        # ── Step 1: Required-field validation (works on raw dict) ────
        field_issues = validate_required_fields(raw)
        all_issues.extend(field_issues)

        # If required fields are missing we can't safely parse the entry;
        # return a REJECT immediately with what we have.
        has_field_errors = any(i.severity == IssueSeverity.ERROR for i in field_issues)

        entry_id = str(raw.get("id", "<unknown>")).strip()

        if has_field_errors:
            return EntryResult(
                entry_id=entry_id,
                description=str(raw.get("description", "")),
                date=str(raw.get("date", "")),
                source=str(raw.get("source", "")),
                original_lines=[],
                total_debit=Decimal("0"),
                total_credit=Decimal("0"),
                difference=Decimal("0"),
                errors=[i.message for i in all_issues if i.severity == IssueSeverity.ERROR],
                warnings=[i.message for i in all_issues if i.severity == IssueSeverity.WARNING],
                account_checks=[],
                status=EntryStatus.REJECT,
                explanation=self._fallback_explanation(entry_id, all_issues),
            )

        # ── Step 2: Parse into typed model ───────────────────────────
        try:
            entry = RawJournalEntry(**raw)
        except Exception as exc:
            all_issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                validator="Parser",
                message=f"[{entry_id}] Entry could not be parsed: {exc}",
            ))
            return EntryResult(
                entry_id=entry_id,
                description=str(raw.get("description", "")),
                date=str(raw.get("date", "")),
                source=str(raw.get("source", "")),
                original_lines=[],
                total_debit=Decimal("0"),
                total_credit=Decimal("0"),
                difference=Decimal("0"),
                errors=[i.message for i in all_issues if i.severity == IssueSeverity.ERROR],
                warnings=[],
                account_checks=[],
                status=EntryStatus.REJECT,
                explanation=self._fallback_explanation(entry_id, all_issues),
            )

        # ── Step 3: Deterministic validators ─────────────────────────
        # 3a. Balance
        all_issues.extend(validate_balance(entry))

        # 3b. Accounts
        checks, acct_issues = validate_accounts(entry, self._coa)
        account_checks.extend(checks)
        all_issues.extend(acct_issues)

        # 3c. Duplicate / same-account
        all_issues.extend(validate_duplicates(entry))

        # 3d. Intercompany
        all_issues.extend(validate_intercompany(entry))

        # 3e. Semantic (deterministic rules only)
        all_issues.extend(validate_semantics(entry, self._coa))

        # ── Step 4: Compute arithmetic (always deterministic) ────────
        total_debit, total_credit, difference = compute_totals(entry)

        # ── Step 5: Decide status ────────────────────────────────────
        errors = [i.message for i in all_issues if i.severity == IssueSeverity.ERROR]
        warnings = [i.message for i in all_issues if i.severity == IssueSeverity.WARNING]
        status = self._decide_status(errors, warnings)

        # ── Step 6: Explanation ──────────────────────────────────────
        explanation = self._get_explanation(entry, all_issues, status, explanation_fn)

        # ── Step 7: Human-review fields ──────────────────────────────
        human_review_required = status == EntryStatus.QUARANTINE
        review_reason: str | None = None
        if human_review_required:
            review_reason = self._build_review_reason(entry, warnings)

        return EntryResult(
            entry_id=entry.id,
            description=entry.description,
            date=entry.date,
            source=entry.source,
            original_lines=entry.lines,
            total_debit=total_debit,
            total_credit=total_credit,
            difference=difference,
            errors=errors,
            warnings=warnings,
            account_checks=account_checks,
            status=status,
            explanation=explanation,
            human_review_required=human_review_required,
            review_reason=review_reason,
        )

    # ------------------------------------------------------------------
    # Status decision (fully deterministic)
    # ------------------------------------------------------------------

    @staticmethod
    def _decide_status(errors: list[str], warnings: list[str]) -> EntryStatus:
        if errors:
            return EntryStatus.REJECT
        if warnings:
            return EntryStatus.QUARANTINE
        return EntryStatus.ACCEPT

    # ------------------------------------------------------------------
    # Explanation helpers
    # ------------------------------------------------------------------

    def _get_explanation(
        self,
        entry: RawJournalEntry,
        issues: list[ValidationIssue],
        status: EntryStatus,
        explanation_fn: Optional[callable],
    ) -> str:
        if explanation_fn is not None:
            try:
                result = explanation_fn(entry, issues, status)
                if result is not None:
                    return str(result)
            except Exception as exc:
                logger.warning(
                    "LLM explanation failed for %s: %s — using fallback",
                    entry.id, exc,
                )
        return self._fallback_explanation(entry.id, issues)

    @staticmethod
    def _fallback_explanation(
        entry_id: str,
        issues: list[ValidationIssue],
    ) -> str:
        """
        Generate a plain-English explanation without an LLM.

        This is always available even when no API key is configured.
        """
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        warnings = [i for i in issues if i.severity == IssueSeverity.WARNING]

        if not issues:
            return (
                f"Entry {entry_id} passed all validation checks. "
                "Debits equal credits, all account codes are valid and postable, "
                "and no suspicious patterns were detected."
            )

        parts: list[str] = [f"Entry {entry_id} was reviewed and the following findings were identified."]

        if errors:
            parts.append(
                f"ERRORS ({len(errors)}): " + " | ".join(e.message for e in errors)
            )
        if warnings:
            parts.append(
                f"WARNINGS ({len(warnings)}): " + " | ".join(w.message for w in warnings)
            )

        if errors:
            parts.append(
                "This entry has been REJECTED and must be corrected before posting."
            )
        else:
            parts.append(
                "This entry is mathematically valid but has been flagged for "
                "human review before it can be approved for posting."
            )

        return "  ".join(parts)

    @staticmethod
    def _build_review_reason(
        entry: RawJournalEntry,
        warnings: list[str],
    ) -> str:
        """Build the human_review_required / review_reason block."""
        lines = [
            f"Entry {entry.id} requires human review before it can be posted.",
            f"Description: {entry.description}",
            f"Source: {entry.source}",
            "Issues requiring review:",
        ]
        for w in warnings:
            lines.append(f"  • {w}")
        lines.append(
            "Suggested action: review the original source documentation, "
            "confirm all account codes are correct, and obtain controller sign-off."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # In-memory entry point (for file-upload workflow)
    # ------------------------------------------------------------------

    def process_batch_from_data(
        self,
        raw_data: dict,
        explanation_fn: Optional[callable] = None,
    ) -> BatchResult:
        """
        Validate a batch supplied as an already-parsed dict.

        This is the entry point used by the Streamlit upload workflow.
        No file I/O is performed — the caller is responsible for loading
        and parsing the JSON.  The source data is never modified.

        Parameters
        ----------
        raw_data : dict
            Parsed content of a manual_adjustments.json-compatible structure.
            Expected keys: period, functional_currency, entries.
        explanation_fn : optional callable
            Same contract as process_batch().
        """
        if not isinstance(raw_data, dict):
            raise ValueError(
                "Adjustments data must be a JSON object with 'entries' key, "
                f"got {type(raw_data).__name__}."
            )

        period = raw_data.get("period", "unknown")
        functional_currency = raw_data.get("functional_currency", "USD")
        raw_entries: list[dict] = raw_data.get("entries", [])

        if not isinstance(raw_entries, list):
            raise ValueError("'entries' must be a list of journal entry objects.")

        logger.info(
            "process_batch_from_data: period=%s, functional_currency=%s, entries=%d",
            period, functional_currency, len(raw_entries),
        )

        results: list[EntryResult] = []
        for raw in raw_entries:
            result = self._process_entry(raw, explanation_fn)
            results.append(result)
            logger.debug(
                "  %s → %s  (errors=%d, warnings=%d)",
                result.entry_id, result.status.value,
                result.error_count, result.warning_count,
            )

        return BatchResult(
            period=period,
            functional_currency=functional_currency,
            results=results,
        )

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json(path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"Adjustments file not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a JSON object at the top level of {path}, "
                f"got {type(data).__name__}."
            )
        return data
