"""
FX validator — kept as a lightweight stub.

The assignment's manual_adjustments.json entries are all in USD with no
explicit currency field per line.  FX-specific validation (rate lookup,
translation arithmetic) is not in scope for the manual-adjustments slice.

This module is preserved for future extension and to satisfy the import
chain expected by tests.
"""

from __future__ import annotations

from app.models.schemas import IssueSeverity, RawJournalEntry, ValidationIssue


def validate_fx(entry: RawJournalEntry) -> list[ValidationIssue]:
    """
    Placeholder FX validator — always returns empty list for USD-only entries.

    Extend this when multi-currency journal entry support is added.
    """
    return []
