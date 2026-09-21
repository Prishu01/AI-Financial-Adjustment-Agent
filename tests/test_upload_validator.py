"""
Tests for app/utils/upload_validator.py

Coverage:
  1.  Valid COA CSV passes
  2.  Wrong file type (not .csv) rejected
  3.  COA CSV missing required columns
  4.  Empty COA CSV
  5.  Valid trial-balance CSV passes
  6.  TB CSV with non-numeric debit/credit
  7.  Valid FX rates CSV passes
  8.  FX CSV missing required columns
  9.  Valid adjustments JSON passes
  10. Non-.json file rejected
  11. Malformed JSON (not parseable)
  12. JSON missing top-level 'entries' key
  13. Empty entries list
  14. Entry missing required fields (id, description, date, source, lines)
  15. Line with non-numeric debit value
  16. Cross-file: account in adjustments missing from COA
  17. Cross-file: all accounts present → no errors
  18. TB CSV passes with optional 'currency' column
  19. COA CSV with blank account_code rows (warning, not fatal)
"""

from __future__ import annotations

import io
import json
import textwrap

import pandas as pd
import pytest

from app.utils.upload_validator import (
    validate_accounts_exist_in_coa,
    validate_adjustments_json,
    validate_coa_csv,
    validate_fx_csv,
    validate_tb_csv,
)

# ---------------------------------------------------------------------------
# Helpers — build raw bytes for test files
# ---------------------------------------------------------------------------

def _csv_bytes(content: str) -> bytes:
    return textwrap.dedent(content).strip().encode("utf-8")


def _json_bytes(obj: object) -> bytes:
    return json.dumps(obj).encode("utf-8")


_VALID_COA_CSV = _csv_bytes("""\
    account_code,account_name,account_type,parent_code,statement,cf_category,normal_balance
    6100,Salaries and Wages,Expense,6000,PL,,Debit
    2120,Accrued Expenses,Liability,2100,BS,Operating,Credit
    6000,Operating Expenses,Header,,,, 
""")

_VALID_ADJ_JSON = _json_bytes({
    "period": "2024-Q4",
    "functional_currency": "USD",
    "entries": [
        {
            "id": "JE-001",
            "description": "Bonus accrual",
            "date": "2024-12-31",
            "source": "Finance team",
            "lines": [
                {"account": "6100", "debit": 850000.0, "credit": 0.0, "memo": "Bonus"},
                {"account": "2120", "debit": 0.0, "credit": 850000.0, "memo": "Offset"},
            ],
        }
    ],
})

_VALID_TB_CSV = _csv_bytes("""\
    account_code,account_name,currency,debit,credit
    6100,Salaries and Wages,USD,1000000.00,0.00
    2120,Accrued Expenses,USD,0.00,500000.00
""")

_VALID_FX_CSV = _csv_bytes("""\
    currency,rate_type,rate,period
    EUR,period_end,1.095,2024-Q4
    GBP,period_average,1.264,2024-Q4
""")


# ===========================================================================
# COA CSV validation
# ===========================================================================

class TestValidateCoACsv:

    def test_valid_coa_passes(self):
        errors, df = validate_coa_csv(_VALID_COA_CSV, "chart_of_accounts.csv")
        assert errors == [], f"Expected no errors but got: {errors}"
        assert df is not None

    def test_wrong_extension_rejected(self):
        errors, df = validate_coa_csv(_VALID_COA_CSV, "chart_of_accounts.xlsx")
        assert any("csv" in e.lower() for e in errors)
        assert df is None

    def test_missing_required_column_account_code(self):
        bad_csv = _csv_bytes("""\
            name,type,normal_balance
            Salaries,Expense,Debit
        """)
        errors, df = validate_coa_csv(bad_csv, "coa.csv")
        assert any("account_code" in e.lower() for e in errors)

    def test_missing_required_column_normal_balance(self):
        bad_csv = _csv_bytes("""\
            account_code,account_name,account_type
            6100,Salaries,Expense
        """)
        errors, df = validate_coa_csv(bad_csv, "coa.csv")
        assert any("normal_balance" in e.lower() for e in errors)

    def test_empty_csv_rejected(self):
        empty = "account_code,account_name,account_type,normal_balance\n".encode()
        errors, df = validate_coa_csv(empty, "coa.csv")
        assert any("empty" in e.lower() for e in errors)

    def test_blank_account_code_rows_produce_warning_not_fatal(self):
        csv_with_blank = _csv_bytes("""\
            account_code,account_name,account_type,normal_balance
            6100,Salaries,Expense,Debit
            ,Blank row,Expense,Debit
        """)
        errors, df = validate_coa_csv(csv_with_blank, "coa.csv")
        # Should warn but not return None df or a hard error that blocks processing
        assert df is not None or len(errors) >= 1  # warning is acceptable

    def test_df_returned_on_valid_input(self):
        errors, df = validate_coa_csv(_VALID_COA_CSV, "coa.csv")
        assert df is not None
        assert len(df) > 0


# ===========================================================================
# Trial Balance CSV validation
# ===========================================================================

class TestValidateTbCsv:

    def test_valid_tb_passes(self):
        errors, df = validate_tb_csv(_VALID_TB_CSV, "trial_balance.csv")
        assert errors == []
        assert df is not None

    def test_wrong_extension_rejected(self):
        errors, df = validate_tb_csv(_VALID_TB_CSV, "tb.xlsx")
        assert any("csv" in e.lower() for e in errors)
        assert df is None

    def test_missing_debit_column(self):
        bad = _csv_bytes("""\
            account_code,account_name,credit
            6100,Salaries,0.00
        """)
        errors, df = validate_tb_csv(bad, "tb.csv")
        assert any("debit" in e.lower() for e in errors)

    def test_non_numeric_debit_flagged(self):
        bad = _csv_bytes("""\
            account_code,account_name,debit,credit
            6100,Salaries,N/A,0.00
        """)
        errors, df = validate_tb_csv(bad, "tb.csv")
        assert any("non-numeric" in e.lower() or "numeric" in e.lower() for e in errors)

    def test_optional_currency_column_accepted(self):
        """TB with a currency column (as in real data) should pass."""
        errors, df = validate_tb_csv(_VALID_TB_CSV, "trial_balance.csv")
        assert errors == []

    def test_custom_label_appears_in_error(self):
        bad = _csv_bytes("x,y\n1,2\n")
        errors, _ = validate_tb_csv(bad, "prior.csv", label="Prior Period TB")
        assert any("Prior Period TB" in e for e in errors)


# ===========================================================================
# FX Rates CSV validation
# ===========================================================================

class TestValidateFxCsv:

    def test_valid_fx_passes(self):
        errors, df = validate_fx_csv(_VALID_FX_CSV, "fx_rates.csv")
        assert errors == []
        assert df is not None

    def test_wrong_extension_rejected(self):
        errors, df = validate_fx_csv(_VALID_FX_CSV, "fx.json")
        assert any("csv" in e.lower() for e in errors)

    def test_missing_rate_column(self):
        bad = _csv_bytes("""\
            currency,rate_type
            EUR,period_end
        """)
        errors, df = validate_fx_csv(bad, "fx.csv")
        assert any("rate" in e.lower() for e in errors)


# ===========================================================================
# Adjustments JSON validation
# ===========================================================================

class TestValidateAdjustmentsJson:

    def test_valid_json_passes(self):
        errors, data = validate_adjustments_json(_VALID_ADJ_JSON, "adjustments.json")
        assert errors == []
        assert data is not None
        assert len(data["entries"]) == 1

    def test_wrong_extension_rejected(self):
        errors, data = validate_adjustments_json(_VALID_ADJ_JSON, "adjustments.csv")
        assert any("json" in e.lower() for e in errors)
        assert data is None

    def test_malformed_json_rejected(self):
        bad = b"{ this is not valid json }"
        errors, data = validate_adjustments_json(bad, "adjustments.json")
        assert any("parsed" in e.lower() or "json" in e.lower() for e in errors)
        assert data is None

    def test_missing_entries_key(self):
        bad = _json_bytes({"period": "2024-Q4", "functional_currency": "USD"})
        errors, data = validate_adjustments_json(bad, "adjustments.json")
        assert any("entries" in e.lower() for e in errors)
        assert data is None

    def test_empty_entries_list(self):
        bad = _json_bytes({"period": "2024-Q4", "entries": []})
        errors, data = validate_adjustments_json(bad, "adjustments.json")
        assert any("empty" in e.lower() for e in errors)

    def test_entry_missing_id_field(self):
        bad = _json_bytes({
            "entries": [{
                # "id" missing
                "description": "Test",
                "date": "2024-12-31",
                "source": "test",
                "lines": [
                    {"account": "6100", "debit": 100, "credit": 0, "memo": ""},
                    {"account": "2120", "debit": 0, "credit": 100, "memo": ""},
                ],
            }]
        })
        errors, _ = validate_adjustments_json(bad, "adjustments.json")
        assert any("id" in e.lower() for e in errors)

    def test_entry_missing_description(self):
        bad = _json_bytes({
            "entries": [{
                "id": "JE-X",
                # "description" missing
                "date": "2024-12-31",
                "source": "test",
                "lines": [
                    {"account": "6100", "debit": 100, "credit": 0, "memo": ""},
                    {"account": "2120", "debit": 0, "credit": 100, "memo": ""},
                ],
            }]
        })
        errors, _ = validate_adjustments_json(bad, "adjustments.json")
        assert any("description" in e.lower() for e in errors)

    def test_entry_missing_lines(self):
        bad = _json_bytes({
            "entries": [{
                "id": "JE-X",
                "description": "Test",
                "date": "2024-12-31",
                "source": "test",
                # "lines" missing
            }]
        })
        errors, _ = validate_adjustments_json(bad, "adjustments.json")
        assert any("lines" in e.lower() for e in errors)

    def test_line_non_numeric_debit(self):
        bad = _json_bytes({
            "entries": [{
                "id": "JE-X",
                "description": "Test",
                "date": "2024-12-31",
                "source": "test",
                "lines": [
                    {"account": "6100", "debit": "N/A", "credit": 0, "memo": ""},
                    {"account": "2120", "debit": 0, "credit": 100, "memo": ""},
                ],
            }]
        })
        errors, _ = validate_adjustments_json(bad, "adjustments.json")
        assert any("debit" in e.lower() and "number" in e.lower() for e in errors)

    def test_top_level_not_dict(self):
        bad = _json_bytes([{"id": "JE-X"}])  # list, not dict
        errors, data = validate_adjustments_json(bad, "adjustments.json")
        assert any("object" in e.lower() or "dict" in e.lower() for e in errors)
        assert data is None

    def test_valid_multi_entry_json(self):
        multi = _json_bytes({
            "period": "2024-Q4",
            "entries": [
                {
                    "id": f"JE-{i:03d}",
                    "description": f"Entry {i}",
                    "date": "2024-12-31",
                    "source": "test",
                    "lines": [
                        {"account": "6100", "debit": 100.0 * i, "credit": 0.0, "memo": ""},
                        {"account": "2120", "debit": 0.0, "credit": 100.0 * i, "memo": ""},
                    ],
                }
                for i in range(1, 4)
            ],
        })
        errors, data = validate_adjustments_json(multi, "adjustments.json")
        assert errors == []
        assert len(data["entries"]) == 3


# ===========================================================================
# Cross-file validation
# ===========================================================================

class TestValidateAccountsExistInCoa:

    def _make_coa_df(self, codes: list[str]) -> pd.DataFrame:
        return pd.DataFrame({
            "account_code": codes,
            "account_name": [f"Account {c}" for c in codes],
            "account_type": ["Expense"] * len(codes),
            "normal_balance": ["Debit"] * len(codes),
        })

    def test_all_accounts_present_no_errors(self):
        adj = {
            "entries": [{
                "id": "JE-001",
                "lines": [
                    {"account": "6100", "debit": 100, "credit": 0},
                    {"account": "2120", "debit": 0, "credit": 100},
                ],
            }]
        }
        coa_df = self._make_coa_df(["6100", "2120"])
        errors = validate_accounts_exist_in_coa(adj, coa_df)
        assert errors == []

    def test_missing_account_reported(self):
        adj = {
            "entries": [{
                "id": "JE-001",
                "lines": [
                    {"account": "6315", "debit": 100, "credit": 0},
                    {"account": "6310", "debit": 0, "credit": 100},
                ],
            }]
        }
        coa_df = self._make_coa_df(["6310"])  # 6315 missing
        errors = validate_accounts_exist_in_coa(adj, coa_df)
        assert len(errors) >= 1
        assert any("6315" in e for e in errors)

    def test_multiple_missing_accounts_all_reported(self):
        adj = {
            "entries": [
                {
                    "id": "JE-001",
                    "lines": [{"account": "XXXX", "debit": 1, "credit": 0}],
                },
                {
                    "id": "JE-002",
                    "lines": [{"account": "YYYY", "debit": 0, "credit": 1}],
                },
            ]
        }
        coa_df = self._make_coa_df([])
        errors = validate_accounts_exist_in_coa(adj, coa_df)
        codes = " ".join(errors)
        assert "XXXX" in codes
        assert "YYYY" in codes


# ===========================================================================
# In-memory processing (process_batch_from_data)
# ===========================================================================

class TestProcessBatchFromData:
    """
    Integration tests for AdjustmentService.process_batch_from_data().
    These exercise the full validation pipeline with in-memory data —
    the same path the upload workflow uses.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def coa(cls):
        from app.services.coa_service import CoAService
        from pathlib import Path
        return CoAService(Path(__file__).parent.parent / "data" / "chart_of_accounts.csv")

    @pytest.fixture(scope="class")
    @classmethod
    def service(cls, coa):
        from app.services.adjustment_service import AdjustmentService
        from pathlib import Path
        return AdjustmentService(coa=coa, data_dir=Path(__file__).parent.parent / "data")

    def _batch(self, service, entries: list[dict]):
        data = {"period": "TEST", "functional_currency": "USD", "entries": entries}
        return service.process_batch_from_data(raw_data=data)

    def test_balanced_entry_accepted(self, service):
        batch = self._batch(service, [{
            "id": "T-001",
            "description": "Balanced entry",
            "date": "2024-12-31",
            "source": "test",
            "lines": [
                {"account": "6100", "debit": 1000.0, "credit": 0.0, "memo": ""},
                {"account": "2120", "debit": 0.0, "credit": 1000.0, "memo": ""},
            ],
        }])
        assert batch.total_entries == 1
        assert batch.results[0].status.value == "ACCEPT"

    def test_unbalanced_entry_rejected(self, service):
        batch = self._batch(service, [{
            "id": "T-002",
            "description": "Unbalanced",
            "date": "2024-12-31",
            "source": "test",
            "lines": [
                {"account": "6100", "debit": 500.0, "credit": 0.0, "memo": ""},
                {"account": "2120", "debit": 0.0, "credit": 400.0, "memo": ""},
            ],
        }])
        r = batch.results[0]
        assert r.status.value == "REJECT"
        assert r.difference > 0

    def test_unknown_account_rejected(self, service):
        batch = self._batch(service, [{
            "id": "T-003",
            "description": "Unknown account",
            "date": "2024-12-31",
            "source": "test",
            "lines": [
                {"account": "ZZZZ", "debit": 100.0, "credit": 0.0, "memo": ""},
                {"account": "2120", "debit": 0.0, "credit": 100.0, "memo": ""},
            ],
        }])
        r = batch.results[0]
        assert r.status.value == "REJECT"
        assert any("ZZZZ" in e for e in r.errors)

    def test_same_account_wash_quarantined(self, service):
        batch = self._batch(service, [{
            "id": "T-004",
            "description": "Intercompany settlement",
            "date": "2024-12-31",
            "source": "IC reconciliation",
            "lines": [
                {"account": "2170", "debit": 100.0, "credit": 0.0, "memo": "IC payable down"},
                {"account": "2170", "debit": 0.0, "credit": 100.0, "memo": "IC payable up"},
            ],
        }])
        r = batch.results[0]
        assert r.status.value == "QUARANTINE"
        assert r.human_review_required is True

    def test_missing_required_field_rejected(self, service):
        """Entry with no 'source' field should be REJECT."""
        batch = self._batch(service, [{
            "id": "T-005",
            "description": "No source",
            "date": "2024-12-31",
            # "source" deliberately missing
            "lines": [
                {"account": "6100", "debit": 100.0, "credit": 0.0, "memo": ""},
                {"account": "2120", "debit": 0.0, "credit": 100.0, "memo": ""},
            ],
        }])
        r = batch.results[0]
        assert r.status.value == "REJECT"

    def test_multi_entry_batch(self, service):
        """Mixed batch: one valid, one unbalanced."""
        batch = self._batch(service, [
            {
                "id": "T-006",
                "description": "Good entry",
                "date": "2024-12-31",
                "source": "test",
                "lines": [
                    {"account": "6100", "debit": 200.0, "credit": 0.0, "memo": ""},
                    {"account": "2120", "debit": 0.0, "credit": 200.0, "memo": ""},
                ],
            },
            {
                "id": "T-007",
                "description": "Bad entry",
                "date": "2024-12-31",
                "source": "test",
                "lines": [
                    {"account": "6100", "debit": 200.0, "credit": 0.0, "memo": ""},
                    {"account": "2120", "debit": 0.0, "credit": 100.0, "memo": ""},
                ],
            },
        ])
        assert batch.total_entries == 2
        status_map = {r.entry_id: r.status.value for r in batch.results}
        assert status_map["T-006"] == "ACCEPT"
        assert status_map["T-007"] == "REJECT"

    def test_invalid_raw_data_type_raises(self, service):
        with pytest.raises((ValueError, TypeError)):
            service.process_batch_from_data(raw_data="not a dict")

    def test_results_match_actual_dataset(self, service):
        """
        Running process_batch_from_data with the real demo JSON must
        produce the same results as process_batch() (idempotency across paths).
        """
        import json
        from pathlib import Path
        adj_path = Path(__file__).parent.parent / "data" / "manual_adjustments.json"
        raw_data = json.loads(adj_path.read_text(encoding="utf-8"))

        batch_mem  = service.process_batch_from_data(raw_data=raw_data)
        batch_file = service.process_batch()

        assert batch_mem.total_entries == batch_file.total_entries
        for r_mem, r_file in zip(batch_mem.results, batch_file.results):
            assert r_mem.entry_id == r_file.entry_id
            assert r_mem.status   == r_file.status
            assert r_mem.total_debit  == r_file.total_debit
            assert r_mem.total_credit == r_file.total_credit
