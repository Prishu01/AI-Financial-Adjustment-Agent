"""
Balance validator.

Deterministically checks that total debits == total credits for a journal
entry.  Uses Python Decimal arithmetic — never delegates to an LLM.

Tolerance: entries are considered balanced if abs(debit - credit) < 0.01
(penny-level rounding).
"""

from __future__ import annotations

from decimal import Decimal

from app.models.schemas import IssueSeverity, RawJournalEntry, ValidationIssue

BALANCE_TOLERANCE = Decimal("0.01")


def validate_balance(entry: RawJournalEntry) -> list[ValidationIssue]:
    """
    Return a list of issues for *entry*.

    An empty list means the entry is balanced within tolerance.
    """
    issues: list[ValidationIssue] = []

    total_debit: Decimal = sum(line.debit for line in entry.lines)
    total_credit: Decimal = sum(line.credit for line in entry.lines)
    diff = abs(total_debit - total_credit)

    if diff >= BALANCE_TOLERANCE:
        issues.append(ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="BalanceValidator",
            message=(
                f"[{entry.id}] Journal entry is unbalanced: "
                f"total debit = {total_debit:,.2f}, "
                f"total credit = {total_credit:,.2f}, "
                f"difference = {diff:,.2f}."
            ),
        ))

    return issues


def compute_totals(entry: RawJournalEntry) -> tuple[Decimal, Decimal, Decimal]:
    """
    Return (total_debit, total_credit, difference) for an entry.

    This is the single source of truth for arithmetic — used by the
    adjustment service to populate EntryResult fields.
    """
    total_debit = sum(line.debit for line in entry.lines)
    total_credit = sum(line.credit for line in entry.lines)
    diff = abs(total_debit - total_credit)
    return total_debit, total_credit, diff
