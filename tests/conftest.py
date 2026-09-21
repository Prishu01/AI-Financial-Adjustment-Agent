"""
Shared pytest fixtures.

Provides:
  - A minimal in-memory CoAService (no file I/O)
  - Factory helpers for building RawJournalEntry objects
  - A real CoAService backed by the actual data/chart_of_accounts.csv
"""

from __future__ import annotations

import csv
import io
import textwrap
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.models.schemas import RawJournalEntry, JournalEntryLine
from app.services.coa_service import CoAService

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"


# ---------------------------------------------------------------------------
# Minimal in-memory CoAService
# ---------------------------------------------------------------------------

_MINIMAL_COA_CSV = textwrap.dedent("""\
    account_code,account_name,account_type,parent_code,statement,cf_category,normal_balance
    6100,Salaries and Wages,Expense,6000,PL,,Debit
    6300,Marketing and Advertising,Expense,6000,PL,,Debit
    6310,Travel and Entertainment,Expense,6000,PL,,Debit
    6400,Professional Fees,Expense,6000,PL,,Debit
    6500,Depreciation Expense,Expense,6000,PL,Operating,Debit
    6510,Amortization Expense,Expense,6000,PL,Operating,Debit
    6600,Bad Debt Expense,Expense,6000,PL,Operating,Debit
    2120,Accrued Expenses,Liability,2100,BS,Operating,Credit
    2140,Current Portion of Long-term Debt,Liability,2100,BS,Financing,Credit
    2170,Intercompany Payable,Liability,2100,BS,TBD,Credit
    2210,Long-term Debt,Liability,2200,BS,Financing,Credit
    1121,Allowance for Doubtful Accounts,Asset,1100,BS,Operating,Credit
    1110,Cash and Cash Equivalents,Asset,1100,BS,Cash,Debit
    1211,Accumulated Depreciation - PPE,Asset,1200,BS,Investing,Credit
    1250,Deferred Tax Asset,Asset,1200,BS,Operating,Debit
    7310,FX Gain/Loss - Unrealized,Expense,7000,PL,Operating,Debit
    8200,Deferred Tax Expense,Expense,8000,PL,Operating,Debit
    6000,Operating Expenses,Header,,,, 
""")


@pytest.fixture(scope="session")
def minimal_coa(tmp_path_factory) -> CoAService:
    """CoAService built from a small in-memory CSV covering only the accounts used in tests."""
    tmp = tmp_path_factory.mktemp("coa")
    path = tmp / "chart_of_accounts.csv"
    path.write_text(_MINIMAL_COA_CSV, encoding="utf-8")
    return CoAService(path)


@pytest.fixture(scope="session")
def real_coa() -> CoAService:
    """CoAService backed by the actual data/chart_of_accounts.csv."""
    return CoAService(DATA_DIR / "chart_of_accounts.csv")


# ---------------------------------------------------------------------------
# Journal entry factory helpers
# ---------------------------------------------------------------------------

def make_entry(
    id: str = "TEST-001",
    description: str = "Test entry",
    date: str = "2024-12-31",
    source: str = "test",
    lines: list[dict] | None = None,
) -> RawJournalEntry:
    """Return a RawJournalEntry with the given fields."""
    if lines is None:
        lines = [
            {"account": "6100", "debit": 1000.0, "credit": 0.0, "memo": "dr"},
            {"account": "2120", "debit": 0.0, "credit": 1000.0, "memo": "cr"},
        ]
    return RawJournalEntry(id=id, description=description, date=date, source=source, lines=lines)


@pytest.fixture
def balanced_entry() -> RawJournalEntry:
    return make_entry(
        id="JE-BALANCED",
        description="Balanced bonus accrual",
        lines=[
            {"account": "6100", "debit": 850000.0, "credit": 0.0, "memo": "Bonus accrual"},
            {"account": "2120", "debit": 0.0, "credit": 850000.0, "memo": "Accrual offset"},
        ],
    )


@pytest.fixture
def unbalanced_entry() -> RawJournalEntry:
    return make_entry(
        id="JE-UNBALANCED",
        description="Unbalanced reclassification",
        lines=[
            {"account": "6300", "debit": 28500.0, "credit": 0.0, "memo": "Move from T&E"},
            {"account": "6310", "debit": 0.0, "credit": 25000.0, "memo": "Reverse from T&E"},
        ],
    )


@pytest.fixture
def unknown_account_entry() -> RawJournalEntry:
    return make_entry(
        id="JE-UNKNOWN-ACCT",
        description="Reclass to non-existent account",
        lines=[
            {"account": "6315", "debit": 18500.0, "credit": 0.0, "memo": "Conf travel"},
            {"account": "6310", "debit": 0.0, "credit": 18500.0, "memo": "Out of T&E"},
        ],
    )


@pytest.fixture
def same_account_entry() -> RawJournalEntry:
    return make_entry(
        id="JE-SAME-ACCT",
        description="Intercompany settlement",
        lines=[
            {"account": "2170", "debit": 320000.0, "credit": 0.0, "memo": "IC payable down"},
            {"account": "2170", "debit": 0.0, "credit": 320000.0, "memo": "IC payable up"},
        ],
    )


@pytest.fixture
def missing_field_entry_raw() -> dict:
    """Raw dict missing the 'source' field."""
    return {
        "id": "JE-NO-SOURCE",
        "description": "Missing source field",
        "date": "2024-12-31",
        # "source" deliberately omitted
        "lines": [
            {"account": "6100", "debit": 1000.0, "credit": 0.0, "memo": "dr"},
            {"account": "2120", "debit": 0.0, "credit": 1000.0, "memo": "cr"},
        ],
    }


@pytest.fixture
def multi_line_entry() -> RawJournalEntry:
    """Three-line compound entry — balanced."""
    return make_entry(
        id="JE-MULTI",
        description="Multi-line compound entry",
        lines=[
            {"account": "6100", "debit": 500000.0, "credit": 0.0, "memo": "Salaries"},
            {"account": "6110", "debit": 100000.0, "credit": 0.0, "memo": "Benefits"},
            {"account": "2120", "debit": 0.0, "credit": 600000.0, "memo": "Accrual"},
        ],
    )
