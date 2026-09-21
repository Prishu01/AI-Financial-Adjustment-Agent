"""
Duplicate / suspicious-line validator.

Checks for two patterns:

1. **Duplicate lines** — two lines with identical (account, debit, credit, memo).
   These are likely copy-paste errors and inflate totals.

2. **Same-account debit+credit** — a single account appears on both the debit
   side and the credit side of the same entry (e.g. JE-008).  The entry may
   balance arithmetically but the net effect on that account is zero, which is
   almost always an error or a suspicious wash entry.

Deterministic — no LLM.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.models.schemas import IssueSeverity, RawJournalEntry, ValidationIssue


def validate_duplicates(entry: RawJournalEntry) -> list[ValidationIssue]:
    """
    Return issues for duplicate lines and same-account debit/credit situations.
    """
    issues: list[ValidationIssue] = []
    issues.extend(_check_duplicate_lines(entry))
    issues.extend(_check_same_account_debit_credit(entry))
    return issues


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_duplicate_lines(entry: RawJournalEntry) -> list[ValidationIssue]:
    """Flag lines that share the same (account, debit, credit, memo)."""
    issues: list[ValidationIssue] = []
    seen: dict[tuple, int] = {}

    for idx, line in enumerate(entry.lines):
        key = (line.account, line.debit, line.credit, line.memo.strip())
        if key in seen:
            issues.append(ValidationIssue(
                severity=IssueSeverity.WARNING,
                validator="DuplicateValidator",
                message=(
                    f"[{entry.id}] Line {idx + 1} is an exact duplicate of line "
                    f"{seen[key] + 1} "
                    f"(account={line.account}, debit={line.debit}, "
                    f"credit={line.credit}, memo='{line.memo}').  "
                    f"Possible copy-paste error."
                ),
                account=line.account,
            ))
        else:
            seen[key] = idx

    return issues


def _check_same_account_debit_credit(entry: RawJournalEntry) -> list[ValidationIssue]:
    """Flag accounts that appear on both debit and credit sides."""
    issues: list[ValidationIssue] = []

    # Accumulate total debits and credits per account
    debit_totals: dict[str, Decimal] = defaultdict(Decimal)
    credit_totals: dict[str, Decimal] = defaultdict(Decimal)

    for line in entry.lines:
        if line.debit > 0:
            debit_totals[line.account] += line.debit
        if line.credit > 0:
            credit_totals[line.account] += line.credit

    both_sides = set(debit_totals.keys()) & set(credit_totals.keys())
    for code in sorted(both_sides):
        dr = debit_totals[code]
        cr = credit_totals[code]
        issues.append(ValidationIssue(
            severity=IssueSeverity.WARNING,
            validator="DuplicateValidator",
            message=(
                f"[{entry.id}] Account '{code}' appears on BOTH the debit side "
                f"(total Dr={dr:,.2f}) and credit side (total Cr={cr:,.2f}) of "
                f"the same entry.  Net effect on this account is "
                f"{abs(dr - cr):,.2f} — review for wash/no-op entries."
            ),
            account=code,
        ))

    return issues
