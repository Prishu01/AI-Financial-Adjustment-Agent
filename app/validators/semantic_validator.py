"""
Semantic validator.

Performs lightweight *deterministic* semantic checks that do not require an
LLM but go beyond pure arithmetic:

1. **Normal-balance violation** — a line debits a Credit-normal account or
   credits a Debit-normal account without apparent reason.  This is flagged
   as a WARNING (not ERROR) because contra entries and reversals are valid.

2. **FX reval account mismatch** — an entry whose description suggests FX
   revaluation but does not touch any recognised FX gain/loss account.

3. **Zero-net wash detection** — if ALL lines for an account net to zero
   within the entry (same total debit and credit), the entry is a complete
   wash and flagged for review.

These are warnings that should be reviewed by a human (QUARANTINE trigger),
not hard rejections.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import re

from app.models.schemas import IssueSeverity, RawJournalEntry, ValidationIssue
from app.services.coa_service import CoAService

# Account codes recognised as FX gain/loss accounts (from actual COA)
_FX_ACCOUNTS: set[str] = {"7300", "7310"}

# Keywords indicating an entry is intended as an FX revaluation
_FX_KEYWORDS = re.compile(r"\bfx\b|\bforeign.?exchange\b|\breval", re.IGNORECASE)


def validate_semantics(
    entry: RawJournalEntry,
    coa: CoAService,
) -> list[ValidationIssue]:
    """
    Return semantic warnings for *entry*.

    All checks here are deterministic rule-based logic.
    """
    issues: list[ValidationIssue] = []
    issues.extend(_check_normal_balance(entry, coa))
    issues.extend(_check_fx_account_usage(entry))
    issues.extend(_check_zero_net_wash(entry))
    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_normal_balance(
    entry: RawJournalEntry,
    coa: CoAService,
) -> list[ValidationIssue]:
    """
    Warn when a line posts against the account's normal balance without a
    clear reversal/contra context.
    """
    issues: list[ValidationIssue] = []
    for line in entry.lines:
        acct = coa.get(line.account)
        if acct is None or not acct.is_postable:
            continue  # missing-account error handled by AccountValidator

        normal = (acct.normal_balance or "").strip().lower()
        if normal == "debit" and line.credit > 0:
            issues.append(ValidationIssue(
                severity=IssueSeverity.WARNING,
                validator="SemanticValidator",
                message=(
                    f"[{entry.id}] Account '{line.account} – {acct.account_name}' "
                    f"has a Debit normal balance but is being credited "
                    f"({line.credit:,.2f}).  Verify this is intentional "
                    f"(e.g. a reversal or contra entry)."
                ),
                account=line.account,
            ))
        elif normal == "credit" and line.debit > 0:
            issues.append(ValidationIssue(
                severity=IssueSeverity.WARNING,
                validator="SemanticValidator",
                message=(
                    f"[{entry.id}] Account '{line.account} – {acct.account_name}' "
                    f"has a Credit normal balance but is being debited "
                    f"({line.debit:,.2f}).  Verify this is intentional "
                    f"(e.g. a write-down, reclassification, or reversal)."
                ),
                account=line.account,
            ))
    return issues


def _check_fx_account_usage(entry: RawJournalEntry) -> list[ValidationIssue]:
    """
    If the description looks like an FX reval, ensure an FX account is used.
    """
    issues: list[ValidationIssue] = []
    if not _FX_KEYWORDS.search(entry.description):
        return issues

    used_accounts = {line.account for line in entry.lines}
    if not used_accounts.intersection(_FX_ACCOUNTS):
        issues.append(ValidationIssue(
            severity=IssueSeverity.WARNING,
            validator="SemanticValidator",
            message=(
                f"[{entry.id}] Entry description suggests FX revaluation "
                f"('{entry.description}') but no FX gain/loss account "
                f"({', '.join(sorted(_FX_ACCOUNTS))}) is used.  "
                f"Verify the correct FX account is included."
            ),
        ))
    return issues


def _check_zero_net_wash(entry: RawJournalEntry) -> list[ValidationIssue]:
    """
    Warn if every account in the entry has net-zero impact
    (complete wash — the entry does nothing).
    """
    issues: list[ValidationIssue] = []
    debit_map: dict[str, Decimal] = defaultdict(Decimal)
    credit_map: dict[str, Decimal] = defaultdict(Decimal)

    for line in entry.lines:
        debit_map[line.account] += line.debit
        credit_map[line.account] += line.credit

    all_accounts = set(debit_map.keys()) | set(credit_map.keys())
    if not all_accounts:
        return issues

    all_zero = all(
        debit_map[a] == credit_map[a] for a in all_accounts
    )
    if all_zero:
        issues.append(ValidationIssue(
            severity=IssueSeverity.WARNING,
            validator="SemanticValidator",
            message=(
                f"[{entry.id}] Every account in this entry has equal debit and "
                f"credit totals — the net effect is zero (complete wash entry).  "
                f"This entry will have no impact on any account balance."
            ),
        ))
    return issues
