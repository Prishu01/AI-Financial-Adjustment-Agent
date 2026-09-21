"""
Pydantic models for the AI Financial Adjustment Agent.

All schemas are built around the ACTUAL data in:
  - manual_adjustments.json  (id, description, date, source, lines[account, debit, credit, memo])
  - chart_of_accounts.csv    (account_code, account_name, account_type, parent_code,
                               statement, cf_category, normal_balance)

No fields are invented.  Every model field corresponds to a real data attribute.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EntryStatus(str, Enum):
    """Final disposition of a validated journal entry."""

    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    QUARANTINE = "QUARANTINE"


class IssueSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------


class CoAAccount(BaseModel):
    """
    One row from chart_of_accounts.csv.

    Columns present in the actual file:
      account_code, account_name, account_type, parent_code,
      statement, cf_category, normal_balance
    """

    account_code: str
    account_name: str
    account_type: str  # Asset, Liability, Equity, Revenue, Expense, Header
    parent_code: Optional[str] = None
    statement: Optional[str] = None   # BS or PL
    cf_category: Optional[str] = None  # Cash, Operating, Investing, Financing, TBD, or blank
    normal_balance: Optional[str] = None  # Debit or Credit (blank for Header rows)

    @property
    def is_header(self) -> bool:
        """Header/rollup accounts must not be posted to."""
        return self.account_type.strip().lower() == "header"

    @property
    def is_postable(self) -> bool:
        """Only non-header accounts with a defined normal balance may be posted to."""
        return not self.is_header and self.normal_balance is not None


# ---------------------------------------------------------------------------
# Journal Entry (raw input, from manual_adjustments.json)
# ---------------------------------------------------------------------------


class JournalEntryLine(BaseModel):
    """
    One line from a manual_adjustments.json entry's ``lines`` array.

    Fields in the actual JSON: account, debit, credit, memo.
    """

    account: str = Field(..., description="Account code referenced by this line")
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)
    memo: str = Field(default="")

    @field_validator("account", mode="before")
    @classmethod
    def coerce_account_to_str(cls, v: object) -> str:
        return str(v).strip()

    @field_validator("debit", "credit", mode="before")
    @classmethod
    def coerce_decimal(cls, v: object) -> Decimal:
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal("0")


class RawJournalEntry(BaseModel):
    """
    One journal entry exactly as it appears in manual_adjustments.json.

    Required fields per spec: id, description, date, source, lines.
    """

    id: str
    description: str
    date: str          # kept as string so we can validate format separately
    source: str
    lines: list[JournalEntryLine]


# ---------------------------------------------------------------------------
# Validation primitives
# ---------------------------------------------------------------------------


class ValidationIssue(BaseModel):
    """A single finding from one validator."""

    severity: IssueSeverity
    validator: str
    message: str
    account: Optional[str] = None   # affected account code, if relevant


class AccountCheck(BaseModel):
    """Per-account result produced during account validation."""

    account: str
    exists_in_coa: bool
    is_postable: bool              # False for Header accounts
    account_type: Optional[str] = None
    normal_balance: Optional[str] = None
    issue: Optional[str] = None    # human-readable problem description, or None


# ---------------------------------------------------------------------------
# Final result per journal entry
# ---------------------------------------------------------------------------


class EntryResult(BaseModel):
    """
    Complete validation result for one journal entry.

    This is the primary output record — one per JE in manual_adjustments.json.
    """

    # ── Identity / traceability ──────────────────────────────────────────
    entry_id: str
    description: str
    date: str
    source: str
    original_lines: list[JournalEntryLine]

    # ── Deterministic arithmetic (never delegated to LLM) ───────────────
    total_debit: Decimal
    total_credit: Decimal
    difference: Decimal            # abs(total_debit - total_credit)

    # ── Validation findings ──────────────────────────────────────────────
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    account_checks: list[AccountCheck] = Field(default_factory=list)

    # ── Final decision ───────────────────────────────────────────────────
    status: EntryStatus

    # ── Human-readable explanation (LLM or fallback) ────────────────────
    explanation: str = ""

    # ── Human-in-the-loop fields (only populated for QUARANTINE) ────────
    human_review_required: bool = False
    review_reason: Optional[str] = None

    # ── Computed helpers ─────────────────────────────────────────────────
    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def to_summary_row(self) -> dict:
        """Return a flat dict suitable for the CSV summary row."""
        return {
            "entry_id": self.entry_id,
            "status": self.status.value,
            "total_debit": float(self.total_debit),
            "total_credit": float(self.total_credit),
            "difference": float(self.difference),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "human_review_required": self.human_review_required,
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------------
# Batch output
# ---------------------------------------------------------------------------


class BatchResult(BaseModel):
    """Aggregated output for all journal entries in the batch."""

    period: str
    functional_currency: str
    generated_at: datetime = Field(default_factory=datetime.now)
    results: list[EntryResult] = Field(default_factory=list)

    @property
    def total_entries(self) -> int:
        return len(self.results)

    @property
    def accepted(self) -> list[EntryResult]:
        return [r for r in self.results if r.status == EntryStatus.ACCEPT]

    @property
    def rejected(self) -> list[EntryResult]:
        return [r for r in self.results if r.status == EntryStatus.REJECT]

    @property
    def quarantined(self) -> list[EntryResult]:
        return [r for r in self.results if r.status == EntryStatus.QUARANTINE]

    @property
    def total_errors(self) -> int:
        return sum(r.error_count for r in self.results)

    @property
    def total_warnings(self) -> int:
        return sum(r.warning_count for r in self.results)
