"""
Explanation Agent.

Uses the LLM provider to generate plain-English explanations of validation
results for finance users.

Contract
--------
* The LLM receives ONLY the pre-computed validation output (status, errors,
  warnings, arithmetic totals).  It does NOT re-do any validation.
* The LLM cannot change the status decision — that is fully deterministic.
* If the LLM is unavailable the service falls back to the deterministic
  explanation produced by AdjustmentService._fallback_explanation().

The explanation is human-facing: written for a financial controller or
auditor who needs to understand why an entry was accepted, rejected, or
quarantined and what action to take.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.llm_provider import LLMProvider
from app.models.schemas import EntryResult, EntryStatus, IssueSeverity, RawJournalEntry, ValidationIssue

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior financial reporting expert reviewing journal entry validation results.

Your task is to write a SHORT (3–5 sentence) plain-English explanation for a finance \
user explaining:
1. What the journal entry was trying to do.
2. Why it was ACCEPTED, REJECTED, or flagged for QUARANTINE.
3. What the finance user should do next (if anything).

Rules you must follow:
- Do NOT re-calculate any numbers. Use only the figures provided to you.
- Do NOT change or question the validation decision.  It is final.
- Write for a financial controller — professional but clear.
- Do NOT use bullet points. Write flowing sentences.
- Keep the response under 100 words.
"""


def build_explanation_fn(provider: LLMProvider) -> callable:
    """
    Return a callable that matches the signature expected by AdjustmentService:

        explanation_fn(entry, issues, status) -> str

    If the LLM is unavailable the callable returns None and the service
    uses its own fallback.
    """

    def _explain(
        entry: RawJournalEntry,
        issues: list[ValidationIssue],
        status: EntryStatus,
    ) -> Optional[str]:
        if not provider.is_available:
            return None  # signal to use deterministic fallback

        errors = [i.message for i in issues if i.severity == IssueSeverity.ERROR]
        warnings = [i.message for i in issues if i.severity == IssueSeverity.WARNING]

        user_prompt = _build_prompt(entry, status, errors, warnings)
        response = provider.complete(_SYSTEM_PROMPT, user_prompt)

        if not response or not response.strip():
            return None

        return response.strip()

    return _explain


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    entry: RawJournalEntry,
    status: EntryStatus,
    errors: list[str],
    warnings: list[str],
) -> str:
    lines: list[str] = [
        f"Journal Entry ID : {entry.id}",
        f"Description      : {entry.description}",
        f"Date             : {entry.date}",
        f"Source           : {entry.source}",
        f"Validation Status: {status.value}",
        "",
        "Lines:",
    ]
    for line in entry.lines:
        side = f"Dr {line.debit:,.2f}" if line.debit > 0 else f"Cr {line.credit:,.2f}"
        lines.append(f"  Account {line.account} — {side}  (memo: {line.memo})")

    if errors:
        lines.append("")
        lines.append("Errors found:")
        for e in errors:
            lines.append(f"  - {e}")

    if warnings:
        lines.append("")
        lines.append("Warnings found:")
        for w in warnings:
            lines.append(f"  - {w}")

    lines.append("")
    lines.append("Write the explanation now.")
    return "\n".join(lines)
