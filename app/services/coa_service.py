"""
Chart of Accounts Service.

Loads chart_of_accounts.csv and provides fast lookup by account code.
The CSV columns are:
  account_code, account_name, account_type, parent_code,
  statement, cf_category, normal_balance

Rules derived from the actual data:
  - account_type == "Header" means the row is a rollup node, not postable.
  - normal_balance is "Debit" or "Credit" for postable accounts; blank for Headers.
  - No invented fields.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from app.models.schemas import CoAAccount

logger = logging.getLogger(__name__)


class CoAService:
    """Loads and queries the Chart of Accounts."""

    def __init__(self, coa_path: str | Path) -> None:
        self._path = Path(coa_path)
        self._accounts: dict[str, CoAAccount] = {}
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Parse the CSV into CoAAccount objects, tolerating missing columns."""
        if not self._path.exists():
            raise FileNotFoundError(f"Chart of Accounts not found: {self._path}")

        df = pd.read_csv(self._path, dtype=str)
        df.columns = [c.strip() for c in df.columns]

        # Normalise: strip whitespace from all string cells
        df = df.apply(lambda col: col.str.strip() if col.dtype == object else col)

        for _, row in df.iterrows():
            code = str(row.get("account_code", "")).strip()
            if not code:
                continue

            account = CoAAccount(
                account_code=code,
                account_name=str(row.get("account_name", "")).strip(),
                account_type=str(row.get("account_type", "")).strip(),
                parent_code=self._optional_str(row.get("parent_code")),
                statement=self._optional_str(row.get("statement")),
                cf_category=self._optional_str(row.get("cf_category")),
                normal_balance=self._optional_str(row.get("normal_balance")),
            )
            self._accounts[code] = account

        logger.info("CoA loaded: %d accounts from %s", len(self._accounts), self._path)

    @staticmethod
    def _optional_str(value: object) -> Optional[str]:
        if value is None or (isinstance(value, float) and str(value) == "nan"):
            return None
        s = str(value).strip()
        return s if s else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, code: str) -> Optional[CoAAccount]:
        """Return the CoAAccount for *code*, or None if not found."""
        return self._accounts.get(str(code).strip())

    def exists(self, code: str) -> bool:
        """True if code is present in the COA (regardless of type)."""
        return str(code).strip() in self._accounts

    def is_postable(self, code: str) -> bool:
        """True if the account exists and is not a Header rollup."""
        acct = self.get(code)
        return acct is not None and acct.is_postable

    @property
    def all_codes(self) -> set[str]:
        return set(self._accounts.keys())

    @property
    def all_accounts(self) -> list[CoAAccount]:
        return list(self._accounts.values())

    @property
    def postable_accounts(self) -> list[CoAAccount]:
        return [a for a in self._accounts.values() if a.is_postable]
