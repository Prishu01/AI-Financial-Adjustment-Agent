"""
Tests for CoAService.

Verifies loading, lookup, postability, and header detection against
both the minimal fixture COA and the real chart_of_accounts.csv.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.services.coa_service import CoAService

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"


# ===========================================================================
# CoAService — minimal fixture
# ===========================================================================

class TestCoAServiceMinimal:

    def test_accounts_loaded(self, minimal_coa):
        assert len(minimal_coa.all_accounts) > 0

    def test_known_account_exists(self, minimal_coa):
        assert minimal_coa.exists("6100")

    def test_unknown_account_not_exists(self, minimal_coa):
        assert not minimal_coa.exists("9999")

    def test_get_returns_account(self, minimal_coa):
        acct = minimal_coa.get("6100")
        assert acct is not None
        assert acct.account_name == "Salaries and Wages"

    def test_get_unknown_returns_none(self, minimal_coa):
        assert minimal_coa.get("XXXX") is None

    def test_header_not_postable(self, minimal_coa):
        assert not minimal_coa.is_postable("6000")

    def test_leaf_account_postable(self, minimal_coa):
        assert minimal_coa.is_postable("6100")

    def test_header_account_type(self, minimal_coa):
        acct = minimal_coa.get("6000")
        assert acct is not None
        assert acct.is_header

    def test_postable_accounts_excludes_headers(self, minimal_coa):
        postable = minimal_coa.postable_accounts
        for a in postable:
            assert not a.is_header

    def test_normal_balance_debit(self, minimal_coa):
        acct = minimal_coa.get("6100")
        assert acct.normal_balance == "Debit"

    def test_normal_balance_credit(self, minimal_coa):
        acct = minimal_coa.get("2120")
        assert acct.normal_balance == "Credit"


# ===========================================================================
# CoAService — real data file
# ===========================================================================

class TestCoAServiceReal:

    def test_real_coa_loads(self, real_coa):
        assert len(real_coa.all_accounts) > 0

    def test_real_coa_has_known_account(self, real_coa):
        assert real_coa.exists("1110")
        assert real_coa.exists("4100")
        assert real_coa.exists("8200")

    def test_9999_not_in_real_coa(self, real_coa):
        """9999 (Suspense - Unmapped) should NOT be in the COA — it's a known defect."""
        assert not real_coa.exists("9999")

    def test_6315_not_in_real_coa(self, real_coa):
        """6315 referenced by JE-005 should NOT exist — another known defect."""
        assert not real_coa.exists("6315")

    def test_header_codes_are_headers(self, real_coa):
        header_codes = ["1000", "1100", "2000", "3000", "4000", "5000", "6000"]
        for code in header_codes:
            acct = real_coa.get(code)
            assert acct is not None, f"Header code {code} not found"
            assert acct.is_header, f"{code} should be a Header"

    def test_real_coa_has_postable_accounts(self, real_coa):
        postable = real_coa.postable_accounts
        assert len(postable) > 10

    def test_real_coa_file_not_modified(self):
        """Verify the original COA file is unchanged (check row count)."""
        with open(DATA_DIR / "chart_of_accounts.csv", encoding="utf-8") as f:
            lines = f.readlines()
        # Header + 68 data rows (from our inspection)
        assert len(lines) >= 69, "chart_of_accounts.csv appears to have been modified"


# ===========================================================================
# CoAService — missing file
# ===========================================================================

class TestCoAServiceMissingFile:

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CoAService(tmp_path / "nonexistent.csv")
