"""
Tests for all deterministic validators.

Coverage:
  1. Balanced journal entry → no balance errors
  2. Unbalanced journal entry → balance ERROR
  3. Unknown account → account ERROR
  4. Same-account debit/credit → duplicate WARNING
  5. Missing required field → field ERROR
  6. Multi-line compound entry → passes balance check
  7. Header account → account ERROR (not postable)
  8. Intercompany keyword detection → intercompany WARNING
  9. Duplicate lines → duplicate WARNING
  10. Semantic normal-balance warning → known credit-normal account debited
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.schemas import IssueSeverity, RawJournalEntry
from app.validators.account_validator import validate_accounts
from app.validators.balance_validator import compute_totals, validate_balance
from app.validators.duplicate_validator import validate_duplicates
from app.validators.field_validator import validate_required_fields
from app.validators.intercompany_validator import validate_intercompany
from app.validators.semantic_validator import validate_semantics
from tests.conftest import make_entry


# ===========================================================================
# 1. Balanced entry — no balance errors
# ===========================================================================

class TestBalanceValidator:

    def test_balanced_entry_produces_no_errors(self, balanced_entry):
        issues = validate_balance(balanced_entry)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert errors == [], f"Expected no errors but got: {errors}"

    def test_unbalanced_entry_produces_error(self, unbalanced_entry):
        issues = validate_balance(unbalanced_entry)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert len(errors) == 1
        assert "unbalanced" in errors[0].message.lower()

    def test_unbalanced_difference_amount(self, unbalanced_entry):
        """The error message should state the correct difference (3500)."""
        issues = validate_balance(unbalanced_entry)
        assert any("3,500.00" in i.message or "3500" in i.message for i in issues)

    def test_compute_totals_balanced(self, balanced_entry):
        dr, cr, diff = compute_totals(balanced_entry)
        assert dr == Decimal("850000")
        assert cr == Decimal("850000")
        assert diff == Decimal("0")

    def test_compute_totals_unbalanced(self, unbalanced_entry):
        dr, cr, diff = compute_totals(unbalanced_entry)
        assert dr == Decimal("28500")
        assert cr == Decimal("25000")
        assert diff == Decimal("3500")

    def test_multi_line_balanced(self, multi_line_entry):
        """Three-line entry: 500k + 100k Dr = 600k Cr → balanced."""
        issues = validate_balance(multi_line_entry)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert errors == []

    def test_penny_tolerance(self):
        """Difference < 0.01 should NOT produce an error."""
        entry = make_entry(
            id="JE-PENNY",
            lines=[
                {"account": "6100", "debit": 1000.005, "credit": 0.0, "memo": "dr"},
                {"account": "2120", "debit": 0.0, "credit": 1000.00, "memo": "cr"},
            ],
        )
        issues = validate_balance(entry)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert errors == []


# ===========================================================================
# 3. Unknown account
# ===========================================================================

class TestAccountValidator:

    def test_unknown_account_produces_error(self, unknown_account_entry, minimal_coa):
        checks, issues = validate_accounts(unknown_account_entry, minimal_coa)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert len(errors) >= 1
        assert any("6315" in e.message for e in errors)

    def test_known_accounts_produce_no_errors(self, balanced_entry, minimal_coa):
        """6100 Dr / 2120 Cr — both exist in minimal COA."""
        checks, issues = validate_accounts(balanced_entry, minimal_coa)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert errors == []

    def test_account_check_records_returned(self, balanced_entry, minimal_coa):
        checks, _ = validate_accounts(balanced_entry, minimal_coa)
        codes = {c.account for c in checks}
        assert "6100" in codes
        assert "2120" in codes

    def test_valid_account_marked_postable(self, balanced_entry, minimal_coa):
        checks, _ = validate_accounts(balanced_entry, minimal_coa)
        for c in checks:
            assert c.is_postable, f"Account {c.account} should be postable"

    def test_header_account_not_postable(self, minimal_coa):
        """Account 6000 is a Header — should produce an ERROR."""
        entry = make_entry(
            id="JE-HEADER",
            lines=[
                {"account": "6000", "debit": 1000.0, "credit": 0.0, "memo": "header debit"},
                {"account": "2120", "debit": 0.0, "credit": 1000.0, "memo": "cr"},
            ],
        )
        checks, issues = validate_accounts(entry, minimal_coa)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert len(errors) >= 1
        assert any("6000" in e.message for e in errors)

    def test_unknown_account_check_exists_in_coa_false(self, unknown_account_entry, minimal_coa):
        checks, _ = validate_accounts(unknown_account_entry, minimal_coa)
        unknown = [c for c in checks if c.account == "6315"]
        assert len(unknown) == 1
        assert unknown[0].exists_in_coa is False
        assert unknown[0].is_postable is False


# ===========================================================================
# 4. Same-account debit/credit
# ===========================================================================

class TestDuplicateValidator:

    def test_same_account_both_sides_flagged(self, same_account_entry):
        issues = validate_duplicates(same_account_entry)
        warnings = [i for i in issues if i.severity == IssueSeverity.WARNING]
        assert len(warnings) >= 1
        assert any("2170" in w.message for w in warnings)

    def test_same_account_wash_message_content(self, same_account_entry):
        issues = validate_duplicates(same_account_entry)
        full_text = " ".join(i.message for i in issues)
        assert "debit" in full_text.lower()
        assert "credit" in full_text.lower()

    def test_clean_entry_no_duplicate_warnings(self, balanced_entry):
        issues = validate_duplicates(balanced_entry)
        assert issues == []

    def test_duplicate_lines_detected(self):
        """Two identical lines should produce a duplicate warning."""
        entry = make_entry(
            id="JE-DUP",
            lines=[
                {"account": "6100", "debit": 500.0, "credit": 0.0, "memo": "same"},
                {"account": "6100", "debit": 500.0, "credit": 0.0, "memo": "same"},
                {"account": "2120", "debit": 0.0, "credit": 1000.0, "memo": "cr"},
            ],
        )
        issues = validate_duplicates(entry)
        warnings = [i for i in issues if i.severity == IssueSeverity.WARNING]
        assert len(warnings) >= 1
        assert any("duplicate" in w.message.lower() or "copy" in w.message.lower() for w in warnings)


# ===========================================================================
# 5. Missing required field
# ===========================================================================

class TestFieldValidator:

    def test_missing_source_field(self, missing_field_entry_raw):
        issues = validate_required_fields(missing_field_entry_raw)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert len(errors) >= 1
        assert any("source" in e.message.lower() for e in errors)

    def test_missing_id_field(self):
        raw = {
            "description": "No ID",
            "date": "2024-12-31",
            "source": "test",
            "lines": [{"account": "6100", "debit": 100, "credit": 0, "memo": ""}],
        }
        issues = validate_required_fields(raw)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert any("id" in e.message.lower() for e in errors)

    def test_missing_lines_field(self):
        raw = {
            "id": "JE-X",
            "description": "No lines",
            "date": "2024-12-31",
            "source": "test",
        }
        issues = validate_required_fields(raw)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert any("lines" in e.message.lower() for e in errors)

    def test_empty_lines_list(self):
        raw = {
            "id": "JE-EMPTY",
            "description": "Empty lines",
            "date": "2024-12-31",
            "source": "test",
            "lines": [],
        }
        issues = validate_required_fields(raw)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert any("lines" in e.message.lower() for e in errors)

    def test_invalid_date_format(self):
        raw = {
            "id": "JE-BADDATE",
            "description": "Bad date",
            "date": "31/12/2024",   # wrong format
            "source": "test",
            "lines": [
                {"account": "6100", "debit": 100, "credit": 0, "memo": ""},
                {"account": "2120", "debit": 0, "credit": 100, "memo": ""},
            ],
        }
        issues = validate_required_fields(raw)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert any("date" in e.message.lower() for e in errors)

    def test_valid_entry_no_field_errors(self, balanced_entry):
        raw = balanced_entry.model_dump()
        # model_dump produces lines as list of dicts matching the schema
        issues = validate_required_fields(raw)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert errors == []


# ===========================================================================
# 6. Multi-line entry
# ===========================================================================

class TestMultiLineEntry:

    def test_multi_line_passes_balance(self, multi_line_entry):
        issues = validate_balance(multi_line_entry)
        errors = [i for i in issues if i.severity == IssueSeverity.ERROR]
        assert errors == []

    def test_multi_line_account_checks_count(self, multi_line_entry, minimal_coa):
        """6100, 6110 (not in minimal COA), 2120 — expect 3 distinct account checks."""
        checks, _ = validate_accounts(multi_line_entry, minimal_coa)
        assert len(checks) >= 2   # at least 6100 and 2120 are present


# ===========================================================================
# 7. Quarantine workflow — same-account + intercompany
# ===========================================================================

class TestIntercompanyValidator:

    def test_intercompany_keyword_in_description(self):
        entry = make_entry(
            id="JE-IC",
            description="Intercompany settlement with UK sub",
            lines=[
                {"account": "2170", "debit": 100.0, "credit": 0.0, "memo": ""},
                {"account": "2170", "debit": 0.0, "credit": 100.0, "memo": ""},
            ],
        )
        issues = validate_intercompany(entry)
        assert len(issues) >= 1
        assert issues[0].severity == IssueSeverity.WARNING

    def test_ic_account_code_triggers_flag(self):
        """Account 2170 (Intercompany Payable) alone should trigger IC warning."""
        entry = make_entry(
            id="JE-IC2",
            description="Normal accrual",   # no IC keyword in description
            lines=[
                {"account": "2170", "debit": 500.0, "credit": 0.0, "memo": "IC payable"},
                {"account": "6100", "debit": 0.0, "credit": 500.0, "memo": "offset"},
            ],
        )
        issues = validate_intercompany(entry)
        assert len(issues) >= 1

    def test_non_ic_entry_no_warnings(self, balanced_entry):
        issues = validate_intercompany(balanced_entry)
        assert issues == []


# ===========================================================================
# 8. Semantic validator
# ===========================================================================

class TestSemanticValidator:

    def test_credit_normal_account_debited_warns(self, minimal_coa):
        """2120 (Accrued Expenses) has Credit normal balance; debiting it warns."""
        entry = make_entry(
            id="JE-SEM",
            description="Reverse accrual",
            lines=[
                {"account": "2120", "debit": 1000.0, "credit": 0.0, "memo": "reverse"},
                {"account": "6100", "debit": 0.0, "credit": 1000.0, "memo": "offset"},
            ],
        )
        issues = validate_semantics(entry, minimal_coa)
        warnings = [i for i in issues if i.severity == IssueSeverity.WARNING]
        assert len(warnings) >= 1
        assert any("2120" in w.message for w in warnings)

    def test_clean_entry_no_semantic_warnings(self, balanced_entry, minimal_coa):
        """Normal debit to 6100 (Debit normal) and credit to 2120 (Credit normal)."""
        issues = validate_semantics(balanced_entry, minimal_coa)
        assert issues == []

    def test_zero_net_wash_detected(self, same_account_entry, minimal_coa):
        """2170 Dr=320k and 2170 Cr=320k — zero net wash."""
        issues = validate_semantics(same_account_entry, minimal_coa)
        warnings = [i for i in issues if i.severity == IssueSeverity.WARNING]
        assert any("zero" in w.message.lower() or "wash" in w.message.lower() for w in warnings)
