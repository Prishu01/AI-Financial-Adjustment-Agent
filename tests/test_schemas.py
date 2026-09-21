"""
Tests for Pydantic models in app.models.schemas.

Verifies model construction, validation, computed properties,
and that the output serialisation helpers work correctly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    AccountCheck,
    BatchResult,
    CoAAccount,
    EntryResult,
    EntryStatus,
    IssueSeverity,
    JournalEntryLine,
    RawJournalEntry,
    ValidationIssue,
)
from tests.conftest import make_entry


# ===========================================================================
# CoAAccount
# ===========================================================================

class TestCoAAccount:

    def test_header_account_is_header(self):
        a = CoAAccount(
            account_code="1000",
            account_name="Total Assets",
            account_type="Header",
        )
        assert a.is_header
        assert not a.is_postable

    def test_leaf_account_is_postable(self):
        a = CoAAccount(
            account_code="6100",
            account_name="Salaries",
            account_type="Expense",
            normal_balance="Debit",
        )
        assert not a.is_header
        assert a.is_postable

    def test_account_without_normal_balance_not_postable(self):
        a = CoAAccount(
            account_code="6000",
            account_name="OpEx Header",
            account_type="Header",
            normal_balance=None,
        )
        assert not a.is_postable


# ===========================================================================
# JournalEntryLine
# ===========================================================================

class TestJournalEntryLine:

    def test_debit_line_parsed(self):
        line = JournalEntryLine(account="6100", debit=850000.0, credit=0.0, memo="dr")
        assert line.debit == Decimal("850000")
        assert line.credit == Decimal("0")

    def test_credit_line_parsed(self):
        line = JournalEntryLine(account="2120", debit=0.0, credit=850000.0, memo="cr")
        assert line.credit == Decimal("850000")

    def test_account_coerced_to_string(self):
        line = JournalEntryLine(account=6100, debit=100.0, credit=0.0, memo="")
        assert isinstance(line.account, str)
        assert line.account == "6100"

    def test_decimal_coercion_from_float(self):
        line = JournalEntryLine(account="6100", debit=1234.56, credit=0.0, memo="")
        assert isinstance(line.debit, Decimal)


# ===========================================================================
# RawJournalEntry
# ===========================================================================

class TestRawJournalEntry:

    def test_valid_entry_parsed(self, balanced_entry):
        assert balanced_entry.id == "JE-BALANCED"
        assert len(balanced_entry.lines) == 2

    def test_entry_lines_are_typed(self, balanced_entry):
        for line in balanced_entry.lines:
            assert isinstance(line, JournalEntryLine)

    def test_make_entry_helper(self):
        e = make_entry()
        assert e.id == "TEST-001"


# ===========================================================================
# ValidationIssue
# ===========================================================================

class TestValidationIssue:

    def test_error_issue(self):
        issue = ValidationIssue(
            severity=IssueSeverity.ERROR,
            validator="TestValidator",
            message="Something broke",
        )
        assert issue.severity == IssueSeverity.ERROR

    def test_warning_issue(self):
        issue = ValidationIssue(
            severity=IssueSeverity.WARNING,
            validator="TestValidator",
            message="Something suspicious",
            account="6100",
        )
        assert issue.account == "6100"


# ===========================================================================
# EntryResult
# ===========================================================================

class TestEntryResult:

    def _make_result(
        self,
        status: EntryStatus = EntryStatus.ACCEPT,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> EntryResult:
        return EntryResult(
            entry_id="TEST-001",
            description="Test",
            date="2024-12-31",
            source="test",
            original_lines=[],
            total_debit=Decimal("1000"),
            total_credit=Decimal("1000"),
            difference=Decimal("0"),
            errors=errors or [],
            warnings=warnings or [],
            account_checks=[],
            status=status,
            explanation="Test explanation",
        )

    def test_error_count(self):
        r = self._make_result(errors=["e1", "e2"])
        assert r.error_count == 2

    def test_warning_count(self):
        r = self._make_result(warnings=["w1"])
        assert r.warning_count == 1

    def test_to_summary_row_keys(self):
        r = self._make_result()
        row = r.to_summary_row()
        expected_keys = {
            "entry_id", "status", "total_debit", "total_credit",
            "difference", "error_count", "warning_count",
            "human_review_required", "explanation",
        }
        assert expected_keys == set(row.keys())

    def test_quarantine_sets_human_review(self):
        r = EntryResult(
            entry_id="Q-001",
            description="Q",
            date="2024-12-31",
            source="s",
            original_lines=[],
            total_debit=Decimal("0"),
            total_credit=Decimal("0"),
            difference=Decimal("0"),
            errors=[],
            warnings=["suspicious"],
            account_checks=[],
            status=EntryStatus.QUARANTINE,
            explanation="x",
            human_review_required=True,
            review_reason="Needs review",
        )
        assert r.human_review_required is True
        assert r.review_reason == "Needs review"


# ===========================================================================
# BatchResult
# ===========================================================================

class TestBatchResult:

    def _sample_batch(self) -> BatchResult:
        def _r(eid, status, n_err=0, n_warn=0):
            return EntryResult(
                entry_id=eid,
                description="d",
                date="2024-12-31",
                source="s",
                original_lines=[],
                total_debit=Decimal("100"),
                total_credit=Decimal("100"),
                difference=Decimal("0"),
                errors=["e"] * n_err,
                warnings=["w"] * n_warn,
                account_checks=[],
                status=status,
                explanation="x",
                human_review_required=(status == EntryStatus.QUARANTINE),
            )

        return BatchResult(
            period="2024-Q4",
            functional_currency="USD",
            results=[
                _r("A", EntryStatus.ACCEPT),
                _r("B", EntryStatus.ACCEPT),
                _r("C", EntryStatus.REJECT, n_err=1),
                _r("D", EntryStatus.QUARANTINE, n_warn=2),
            ],
        )

    def test_total_entries(self):
        b = self._sample_batch()
        assert b.total_entries == 4

    def test_accepted_count(self):
        b = self._sample_batch()
        assert len(b.accepted) == 2

    def test_rejected_count(self):
        b = self._sample_batch()
        assert len(b.rejected) == 1

    def test_quarantined_count(self):
        b = self._sample_batch()
        assert len(b.quarantined) == 1

    def test_total_errors(self):
        b = self._sample_batch()
        assert b.total_errors == 1

    def test_total_warnings(self):
        b = self._sample_batch()
        assert b.total_warnings == 2
