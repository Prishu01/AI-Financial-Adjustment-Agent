"""
Upload Validator.

Validates user-supplied files BEFORE they are passed to the validation engine.
Returns friendly, user-facing error messages — no Python stack traces.

Responsibilities
----------------
* File-type checks (CSV vs JSON)
* Required-column checks for CSVs
* JSON structure checks (top-level keys, entries list)
* Numeric sanity on debit/credit columns
* Required journal-entry field presence
* COA account-code availability check (cross-file)

All functions return a list[str] of human-readable error messages.
An empty list means the file passed that check.

Nothing here modifies any uploaded data.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Required columns per file type
# ---------------------------------------------------------------------------

_COA_REQUIRED_COLS = {
    "account_code",
    "account_name",
    "account_type",
    "normal_balance",
}

_TB_REQUIRED_COLS = {
    "account_code",
    "account_name",
    "debit",
    "credit",
}

_PRIOR_TB_REQUIRED_COLS = _TB_REQUIRED_COLS  # same schema

_FX_REQUIRED_COLS = {
    "currency",
    "rate_type",
    "rate",
}

# Required top-level keys in manual_adjustments.json
_ADJ_REQUIRED_KEYS = {"entries"}

# Required fields on every journal entry
_ENTRY_REQUIRED_FIELDS = {"id", "description", "date", "source", "lines"}

# Required fields on every line within a journal entry
_LINE_REQUIRED_FIELDS = {"account", "debit", "credit"}


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def validate_coa_csv(file_bytes: bytes, filename: str) -> tuple[list[str], pd.DataFrame | None]:
    """
    Validate a Chart of Accounts CSV.

    Returns (errors, dataframe).  dataframe is None when errors are fatal.
    """
    errors: list[str] = []

    if not filename.lower().endswith(".csv"):
        errors.append(
            f"'{filename}' does not appear to be a CSV file. "
            "Please upload a .csv file for the Chart of Accounts."
        )
        return errors, None

    try:
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
    except Exception as exc:
        errors.append(f"Could not read '{filename}' as CSV: {exc}")
        return errors, None

    df.columns = [c.strip().lower() for c in df.columns]
    missing = _COA_REQUIRED_COLS - set(df.columns)
    if missing:
        errors.append(
            f"Chart of Accounts CSV is missing required columns: "
            f"{', '.join(sorted(missing))}. "
            f"Found columns: {', '.join(df.columns)}."
        )
        return errors, None

    if len(df) == 0:
        errors.append(f"'{filename}' is empty — no account rows found.")
        return errors, None

    # Warn about rows with blank account_code
    blank_codes = df["account_code"].isna() | (df["account_code"].str.strip() == "")
    if blank_codes.any():
        errors.append(
            f"'{filename}' has {blank_codes.sum()} row(s) with a blank account_code. "
            "These rows will be ignored during processing."
        )

    # Restore original-case column names for the returned df
    df.columns = [c.strip() for c in pd.read_csv(io.BytesIO(file_bytes), nrows=0).columns]
    return errors, df


def validate_tb_csv(
    file_bytes: bytes,
    filename: str,
    label: str = "Trial Balance",
) -> tuple[list[str], pd.DataFrame | None]:
    """Validate a trial-balance CSV (current or prior period)."""
    errors: list[str] = []

    if not filename.lower().endswith(".csv"):
        errors.append(
            f"'{filename}' is not a CSV file. "
            f"Please upload a .csv file for the {label}."
        )
        return errors, None

    try:
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
    except Exception as exc:
        errors.append(f"Could not read '{filename}' as CSV: {exc}")
        return errors, None

    cols_lower = {c.strip().lower() for c in df.columns}
    missing = _TB_REQUIRED_COLS - cols_lower
    if missing:
        errors.append(
            f"{label} CSV is missing required columns: "
            f"{', '.join(sorted(missing))}. "
            f"Found columns: {', '.join(df.columns)}."
        )
        return errors, None

    if len(df) == 0:
        errors.append(f"'{filename}' is empty.")
        return errors, None

    # Check debit/credit are numeric-parseable
    for col in ("debit", "credit"):
        # find actual column name (case-insensitive)
        actual = next((c for c in df.columns if c.strip().lower() == col), None)
        if actual:
            non_numeric = pd.to_numeric(df[actual], errors="coerce").isna()
            if non_numeric.any():
                errors.append(
                    f"{label}: column '{actual}' has {non_numeric.sum()} "
                    "non-numeric value(s). All debit/credit values must be numbers."
                )

    return errors, df


def validate_fx_csv(
    file_bytes: bytes,
    filename: str,
) -> tuple[list[str], pd.DataFrame | None]:
    """Validate an FX rates CSV."""
    errors: list[str] = []

    if not filename.lower().endswith(".csv"):
        errors.append(
            f"'{filename}' is not a CSV file. "
            "Please upload a .csv file for FX Rates."
        )
        return errors, None

    try:
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
    except Exception as exc:
        errors.append(f"Could not read '{filename}' as CSV: {exc}")
        return errors, None

    cols_lower = {c.strip().lower() for c in df.columns}
    missing = _FX_REQUIRED_COLS - cols_lower
    if missing:
        errors.append(
            f"FX Rates CSV is missing required columns: "
            f"{', '.join(sorted(missing))}. "
            f"Found columns: {', '.join(df.columns)}."
        )

    return errors, df


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def validate_adjustments_json(
    file_bytes: bytes,
    filename: str,
) -> tuple[list[str], dict | None]:
    """
    Validate a manual_adjustments.json file.

    Returns (errors, parsed_dict).  parsed_dict is None on fatal errors.
    """
    errors: list[str] = []

    if not filename.lower().endswith(".json"):
        errors.append(
            f"'{filename}' is not a JSON file. "
            "Please upload a .json file for Manual Adjustments."
        )
        return errors, None

    try:
        data = json.loads(file_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        errors.append(
            f"'{filename}' could not be parsed as JSON: {exc}. "
            "Please check the file is valid JSON."
        )
        return errors, None

    if not isinstance(data, dict):
        errors.append(
            f"'{filename}' must be a JSON object (dict) at the top level, "
            f"but got {type(data).__name__}."
        )
        return errors, None

    if "entries" not in data:
        errors.append(
            f"'{filename}' is missing the required 'entries' key. "
            "The file must have the structure: "
            '{"period": "...", "entries": [...]}'
        )
        return errors, None

    if not isinstance(data["entries"], list):
        errors.append(
            f"'{filename}': 'entries' must be a list of journal entry objects."
        )
        return errors, None

    if len(data["entries"]) == 0:
        errors.append(
            f"'{filename}' contains no journal entries. "
            "The 'entries' list is empty."
        )
        return errors, None

    # Per-entry structural checks
    entry_errors = _validate_entry_structures(data["entries"])
    errors.extend(entry_errors)

    return errors, data


def _validate_entry_structures(entries: list[Any]) -> list[str]:
    """Check that each entry has required fields and valid line structure."""
    errors: list[str] = []

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(
                f"Entry at index {i} is not a JSON object — "
                f"got {type(entry).__name__}."
            )
            continue

        entry_id = str(entry.get("id", f"index-{i}"))

        missing_fields = _ENTRY_REQUIRED_FIELDS - set(entry.keys())
        if missing_fields:
            errors.append(
                f"Entry '{entry_id}' is missing required fields: "
                f"{', '.join(sorted(missing_fields))}."
            )

        lines = entry.get("lines")
        if lines is None:
            continue  # already caught by missing_fields

        if not isinstance(lines, list) or len(lines) == 0:
            errors.append(
                f"Entry '{entry_id}': 'lines' must be a non-empty list."
            )
            continue

        for j, line in enumerate(lines):
            if not isinstance(line, dict):
                errors.append(
                    f"Entry '{entry_id}', line {j}: expected a JSON object."
                )
                continue
            missing_line_fields = _LINE_REQUIRED_FIELDS - set(line.keys())
            if missing_line_fields:
                errors.append(
                    f"Entry '{entry_id}', line {j} is missing fields: "
                    f"{', '.join(sorted(missing_line_fields))}."
                )
                continue
            # Check debit/credit are numeric
            for field in ("debit", "credit"):
                val = line.get(field)
                try:
                    float(val)
                except (TypeError, ValueError):
                    errors.append(
                        f"Entry '{entry_id}', line {j}: "
                        f"'{field}' must be a number, got {val!r}."
                    )

    return errors


# ---------------------------------------------------------------------------
# Cross-file validation
# ---------------------------------------------------------------------------

def validate_accounts_exist_in_coa(
    adj_data: dict,
    coa_df: pd.DataFrame,
) -> list[str]:
    """
    Pre-flight check: report any account codes used in adjustments that
    are not present in the uploaded COA.

    This is informational — the engine will also catch this, but surfacing
    it before running gives the user a clearer upload-stage message.
    """
    errors: list[str] = []

    # Normalise COA codes
    code_col = next(
        (c for c in coa_df.columns if c.strip().lower() == "account_code"),
        None,
    )
    if code_col is None:
        return errors

    coa_codes = set(str(v).strip() for v in coa_df[code_col].dropna())

    for entry in adj_data.get("entries", []):
        entry_id = str(entry.get("id", "?"))
        for line in entry.get("lines", []):
            code = str(line.get("account", "")).strip()
            if code and code not in coa_codes:
                errors.append(
                    f"Entry '{entry_id}': account '{code}' is not present "
                    "in the uploaded Chart of Accounts."
                )

    return errors
