"""
Intercompany validator.

Detects entries that involve intercompany activity by scanning the entry's
description, source, and individual line memos for IC-indicator keywords.

When an IC signal is found, the entry is flagged for human review (QUARANTINE).
The check is keyword-driven and deterministic — no LLM.

Keywords are intentionally broad to catch variations in phrasing without
hardcoding specific entry IDs.
"""

from __future__ import annotations

import re

from app.models.schemas import IssueSeverity, RawJournalEntry, ValidationIssue

# Keywords that indicate intercompany activity (case-insensitive)
_IC_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bintercompany\b", re.IGNORECASE),
    re.compile(r"\binter-company\b", re.IGNORECASE),
    re.compile(r"\bic\b", re.IGNORECASE),         # standalone "IC"
    re.compile(r"\bic\s+payable\b", re.IGNORECASE),
    re.compile(r"\bic\s+receivable\b", re.IGNORECASE),
    re.compile(r"\brelated\s+party\b", re.IGNORECASE),
    re.compile(r"\bsubsidiary\b", re.IGNORECASE),
    re.compile(r"\bsub\b", re.IGNORECASE),         # "UK sub", "US sub" etc.
    re.compile(r"\belimination\b", re.IGNORECASE),
    re.compile(r"\bsettlement.*(sub|entity|co\.)\b", re.IGNORECASE),
]

# COA account codes that are intercompany by nature (from actual chart)
_IC_ACCOUNTS: set[str] = {"2170"}  # Intercompany Payable (from chart_of_accounts.csv)


def validate_intercompany(entry: RawJournalEntry) -> list[ValidationIssue]:
    """
    Return issues if the entry shows signs of intercompany activity.

    Detection strategy (any match triggers a WARNING):
    - IC keyword in entry description
    - IC keyword in entry source
    - IC keyword in any line memo
    - Any line references a known IC account code
    """
    issues: list[ValidationIssue] = []
    signals: list[str] = []

    # Check description
    for pat in _IC_PATTERNS:
        if pat.search(entry.description):
            signals.append(f"description contains IC indicator: '{pat.pattern}'")
            break

    # Check source
    for pat in _IC_PATTERNS:
        if pat.search(entry.source):
            signals.append(f"source contains IC indicator: '{pat.pattern}'")
            break

    # Check each line memo and account code
    for line in entry.lines:
        for pat in _IC_PATTERNS:
            if pat.search(line.memo):
                signals.append(
                    f"line memo '{line.memo}' contains IC indicator"
                )
                break
        if line.account in _IC_ACCOUNTS:
            signals.append(
                f"line uses known intercompany account '{line.account}'"
            )

    # Deduplicate signals
    signals = list(dict.fromkeys(signals))

    if signals:
        signal_list = "; ".join(signals)
        issues.append(ValidationIssue(
            severity=IssueSeverity.WARNING,
            validator="IntercompanyValidator",
            message=(
                f"[{entry.id}] Entry shows signs of intercompany activity "
                f"and requires human review before posting. "
                f"Signals detected: {signal_list}."
            ),
        ))

    return issues
