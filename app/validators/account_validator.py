"""
Account validator.

For every line in a journal entry, checks:
  1. The account code exists in the Chart of Accounts.
  2. The account is postable (not a Header rollup node).

Returns one AccountCheck per unique account code referenced by the entry,
plus a flat list of ValidationIssue objects for any failures.

Deterministic — no LLM.
"""

from __future__ import annotations

from app.models.schemas import AccountCheck, IssueSeverity, RawJournalEntry, ValidationIssue
from app.services.coa_service import CoAService


def validate_accounts(
    entry: RawJournalEntry,
    coa: CoAService,
) -> tuple[list[AccountCheck], list[ValidationIssue]]:
    """
    Validate every account code used in *entry* against *coa*.

    Returns
    -------
    account_checks : list[AccountCheck]
        One record per unique account code used in the entry.
    issues : list[ValidationIssue]
        ERROR or WARNING issues found.
    """
    issues: list[ValidationIssue] = []
    checks: list[AccountCheck] = []
    seen: set[str] = set()

    for line in entry.lines:
        code = line.account
        if code in seen:
            continue
        seen.add(code)

        coa_account = coa.get(code)

        if coa_account is None:
            # Account not in COA at all
            checks.append(AccountCheck(
                account=code,
                exists_in_coa=False,
                is_postable=False,
                issue=f"Account '{code}' does not exist in the Chart of Accounts.",
            ))
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                validator="AccountValidator",
                message=(
                    f"[{entry.id}] Account '{code}' referenced in line "
                    f"(memo: '{line.memo}') does not exist in the Chart of Accounts."
                ),
                account=code,
            ))

        elif coa_account.is_header:
            # Account exists but is a Header rollup — not postable
            checks.append(AccountCheck(
                account=code,
                exists_in_coa=True,
                is_postable=False,
                account_type=coa_account.account_type,
                normal_balance=coa_account.normal_balance,
                issue=(
                    f"Account '{code} – {coa_account.account_name}' is a Header "
                    f"(rollup) account and cannot be posted to."
                ),
            ))
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                validator="AccountValidator",
                message=(
                    f"[{entry.id}] Account '{code} – {coa_account.account_name}' "
                    f"is a Header/rollup account and must not be posted to."
                ),
                account=code,
            ))

        else:
            # Account is valid and postable
            checks.append(AccountCheck(
                account=code,
                exists_in_coa=True,
                is_postable=True,
                account_type=coa_account.account_type,
                normal_balance=coa_account.normal_balance,
            ))

    return checks, issues
