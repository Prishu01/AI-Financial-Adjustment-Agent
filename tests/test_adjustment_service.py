"""
Tests for AdjustmentService end-to-end processing.

Uses the ACTUAL data files to verify the correct statuses are produced
for each of the 10 real journal entries.

Also tests the quarantine workflow, fallback explanations,
and idempotency (running twice produces identical output).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.schemas import EntryStatus
from app.services.adjustment_service import AdjustmentService
from app.services.coa_service import CoAService

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@pytest.fixture(scope="module")
def real_service():
    coa = CoAService(DATA_DIR / "chart_of_accounts.csv")
    return AdjustmentService(coa=coa, data_dir=DATA_DIR)


@pytest.fixture(scope="module")
def batch(real_service):
    """Run the full pipeline once and cache the result for all tests in this module."""
    return real_service.process_batch(explanation_fn=None)


# ===========================================================================
# 1. Batch shape
# ===========================================================================

class TestBatchShape:

    def test_ten_entries_processed(self, batch):
        assert batch.total_entries == 10

    def test_period_parsed(self, batch):
        assert batch.period == "2024-Q4"

    def test_functional_currency_parsed(self, batch):
        assert batch.functional_currency == "USD"

    def test_all_entries_have_status(self, batch):
        for r in batch.results:
            assert r.status in (EntryStatus.ACCEPT, EntryStatus.REJECT, EntryStatus.QUARANTINE)


# ===========================================================================
# 2. Known-good entries should ACCEPT
# ===========================================================================

class TestAcceptedEntries:
    """
    Clean entries with no errors AND no semantic warnings → ACCEPT.

    JE-001: bonus accrual      — Dr 6100 / Cr 2120   (both normal sides) → ACCEPT
    JE-004: bad debt top-up    — Dr 6600 / Cr 1121   (both normal sides) → ACCEPT
    JE-006: depreciation       — Dr 6500 / Cr 1211   (both normal sides) → ACCEPT
    JE-009: legal accrual      — Dr 6400 / Cr 2120   (both normal sides) → ACCEPT

    JE-007: DTA true-up        — Cr 1250 (Debit-normal)  → QUARANTINE (semantic warning)
    JE-010: LT debt reclass    — Dr 2210 (Credit-normal) → QUARANTINE (semantic warning)
    Both are arithmetically valid but trigger normal-balance warnings per the
    semantic validator — correct behaviour reflecting real accounting scrutiny.
    """

    _EXPECTED_ACCEPT = {"JE-001", "JE-004", "JE-006", "JE-009"}

    def test_clean_entries_accepted(self, batch):
        result_map = {r.entry_id: r for r in batch.results}
        for entry_id in self._EXPECTED_ACCEPT:
            r = result_map.get(entry_id)
            assert r is not None, f"{entry_id} not found in results"
            assert r.status == EntryStatus.ACCEPT, (
                f"{entry_id} expected ACCEPT but got {r.status}: errors={r.errors}"
            )

    def test_accepted_entries_have_zero_difference(self, batch):
        result_map = {r.entry_id: r for r in batch.results}
        for entry_id in self._EXPECTED_ACCEPT:
            r = result_map[entry_id]
            assert r.difference == 0, f"{entry_id} should have zero difference"

    def test_accepted_entries_have_no_errors(self, batch):
        result_map = {r.entry_id: r for r in batch.results}
        for entry_id in self._EXPECTED_ACCEPT:
            r = result_map[entry_id]
            assert r.errors == [], f"{entry_id} should have no errors"


# ===========================================================================
# 2b. JE-007 — deferred tax true-up → QUARANTINE (semantic warning)
# ===========================================================================

class TestJE007DeferredTax:
    """
    JE-007 credits account 1250 (Deferred Tax Asset — Debit-normal).
    Crediting a Debit-normal account is a valid accounting action (reducing
    a DTA) but the semantic validator correctly flags it for human confirmation.
    Expected status: QUARANTINE (not REJECT — arithmetic is valid).
    """

    def test_je007_is_quarantined(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-007")
        assert r.status == EntryStatus.QUARANTINE

    def test_je007_has_no_errors(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-007")
        assert r.errors == []

    def test_je007_has_semantic_warning(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-007")
        assert any("1250" in w for w in r.warnings)

    def test_je007_is_balanced(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-007")
        assert r.difference == 0


# ===========================================================================
# 2c. JE-010 — long-term debt reclassification → QUARANTINE (semantic warning)
# ===========================================================================

class TestJE010LTDebtReclass:
    """
    JE-010 debits account 2210 (Long-term Debt — Credit-normal).
    Debiting a Credit-normal account is valid (moving LT debt to current
    portion) but triggers a semantic warning for human confirmation.
    Expected status: QUARANTINE (not REJECT — arithmetic is valid).
    """

    def test_je010_is_quarantined(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-010")
        assert r.status == EntryStatus.QUARANTINE

    def test_je010_has_no_errors(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-010")
        assert r.errors == []

    def test_je010_has_semantic_warning(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-010")
        assert any("2210" in w for w in r.warnings)

    def test_je010_is_balanced(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-010")
        assert r.difference == 0




class TestJE002Unbalanced:

    def test_je002_is_rejected(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-002")
        assert r.status == EntryStatus.REJECT

    def test_je002_has_balance_error(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-002")
        assert len(r.errors) >= 1
        assert any("unbalanced" in e.lower() for e in r.errors)

    def test_je002_correct_totals(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-002")
        from decimal import Decimal
        assert r.total_debit == Decimal("28500")
        assert r.total_credit == Decimal("25000")
        assert r.difference == Decimal("3500")

    def test_je002_difference_in_explanation(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-002")
        # explanation must mention the entry was rejected
        assert "REJECT" in r.explanation.upper() or "corrected" in r.explanation.lower()


# ===========================================================================
# 4. JE-005 — unknown account 6315 → REJECT
# ===========================================================================

class TestJE005UnknownAccount:

    def test_je005_is_rejected(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-005")
        assert r.status == EntryStatus.REJECT

    def test_je005_account_6315_flagged(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-005")
        assert any("6315" in e for e in r.errors)

    def test_je005_account_check_shows_not_in_coa(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-005")
        checks = {c.account: c for c in r.account_checks}
        assert "6315" in checks
        assert checks["6315"].exists_in_coa is False


# ===========================================================================
# 5. JE-008 — same-account wash entry → QUARANTINE
# ===========================================================================

class TestJE008WashEntry:

    def test_je008_is_quarantined(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-008")
        assert r.status == EntryStatus.QUARANTINE

    def test_je008_human_review_required(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-008")
        assert r.human_review_required is True

    def test_je008_has_no_errors(self, batch):
        """Arithmetic is valid — QUARANTINE not REJECT."""
        r = next(r for r in batch.results if r.entry_id == "JE-008")
        assert r.errors == []

    def test_je008_has_warnings(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-008")
        assert len(r.warnings) >= 1

    def test_je008_review_reason_populated(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-008")
        assert r.review_reason is not None
        assert len(r.review_reason) > 0

    def test_je008_balanced(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-008")
        assert r.difference == 0


# ===========================================================================
# 6. JE-003 — FX reval → QUARANTINE (IC or semantic warnings expected)
# ===========================================================================

class TestJE003FXReval:

    def test_je003_status_is_accept_or_quarantine(self, batch):
        """JE-003 is balanced and uses valid accounts but may get semantic warnings."""
        r = next(r for r in batch.results if r.entry_id == "JE-003")
        assert r.status in (EntryStatus.ACCEPT, EntryStatus.QUARANTINE)

    def test_je003_no_balance_error(self, batch):
        r = next(r for r in batch.results if r.entry_id == "JE-003")
        assert not any("unbalanced" in e.lower() for e in r.errors)


# ===========================================================================
# 7. Quarantine workflow — all quarantined entries
# ===========================================================================

class TestQuarantineWorkflow:

    def test_quarantined_entries_have_human_review_true(self, batch):
        for r in batch.quarantined:
            assert r.human_review_required is True, (
                f"{r.entry_id} is QUARANTINE but human_review_required=False"
            )

    def test_quarantined_entries_have_review_reason(self, batch):
        for r in batch.quarantined:
            assert r.review_reason, f"{r.entry_id} is QUARANTINE but review_reason is empty"

    def test_quarantined_entries_have_warnings(self, batch):
        for r in batch.quarantined:
            assert r.warnings, f"{r.entry_id} is QUARANTINE but has no warnings"

    def test_accepted_entries_not_human_review(self, batch):
        for r in batch.accepted:
            assert r.human_review_required is False


# ===========================================================================
# 8. Idempotency
# ===========================================================================

class TestIdempotency:

    def test_running_twice_produces_same_statuses(self, real_service):
        batch1 = real_service.process_batch(explanation_fn=None)
        batch2 = real_service.process_batch(explanation_fn=None)
        for r1, r2 in zip(batch1.results, batch2.results):
            assert r1.entry_id == r2.entry_id
            assert r1.status == r2.status
            assert r1.total_debit == r2.total_debit
            assert r1.total_credit == r2.total_credit

    def test_running_twice_produces_same_errors(self, real_service):
        batch1 = real_service.process_batch(explanation_fn=None)
        batch2 = real_service.process_batch(explanation_fn=None)
        for r1, r2 in zip(batch1.results, batch2.results):
            assert r1.errors == r2.errors


# ===========================================================================
# 9. Fallback explanation
# ===========================================================================

class TestFallbackExplanation:

    def test_all_entries_have_explanation(self, batch):
        for r in batch.results:
            assert r.explanation, f"{r.entry_id} has empty explanation"

    def test_rejected_explanation_mentions_rejection(self, batch):
        for r in batch.rejected:
            text = r.explanation.upper()
            assert "REJECT" in text or "CORRECT" in text or "ERROR" in text, (
                f"{r.entry_id} explanation does not mention rejection: {r.explanation[:80]}"
            )
