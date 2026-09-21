# DATA_FINDINGS.md — AI Financial Adjustment Agent

**Period:** 2024-Q4 | **Functional Currency:** USD | **Analysed:** 2026-09-21

---

## 1. trial_balance.csv

| # | Finding | Severity |
|---|---------|----------|
| TB-01 | **Duplicate account row** — Account `6310` (Travel and Entertainment, USD) appears on two separate rows with debits of `245,000` and `38,500`. These must be summed before use; any aggregation that blindly takes the first row will silently understate OpEx by $38,500. | High |
| TB-02 | **Suspense account `9999`** — `Suspense - Unmapped` carries a debit of `$12,400` but code `9999` does not exist in `chart_of_accounts.csv`. The balance cannot be classified, typed, or rolled up. | High |
| TB-03 | **Multi-currency cash rows in local currency** — Account `1110` has three rows: USD `4,250,000`, EUR `825,400`, GBP `412,300`. The EUR and GBP amounts are in their *local* currency and must be translated to USD at the applicable period-end rate before the TB can balance. Until translated, the raw debit total will not equal the raw credit total. | High |
| TB-04 | **Raw debit ≠ raw credit** — Even after collapsing the duplicate `6310` row, the raw USD-as-stated totals do not balance because (a) multi-currency rows are untranslated and (b) the `9999` suspense balance has no offsetting entry visible in this file. This is confirmed by the README. | High |

---

## 2. chart_of_accounts.csv

| # | Finding | Severity |
|---|---------|----------|
| COA-01 | **Account `9999` missing** — Referenced in `trial_balance.csv` as `Suspense - Unmapped` but absent from the COA. Any account validation that requires COA presence will correctly flag this. | High |
| COA-02 | **Account `6315` missing** — Referenced in `manual_adjustments.json` JE-005 as the destination for conference travel but not defined anywhere in the COA. | High |
| COA-03 | **Account `6905` missing from current COA** — `Sundry Operating Expenses` appears in `prior_period_tb.csv` but has no entry in the current COA, making it an orphan prior-period account. | Low |
| COA-04 | **Header/rollup codes mixed with leaf accounts** — Codes `1000`, `1100`, `1200`, `2000`, `2100`, `2200`, `3000`, `4000`, `5000`, `6000`, `7000`, `8000` are typed as `Header` with no `normal_balance`. Posting to a header code should be treated as invalid. | Medium |
| COA-05 | **`7310` typed as Expense with Debit normal balance** — `FX Gain/Loss - Unrealized` is classified as `Expense` with `normal_balance: Debit`, yet it is an unrealised gain/loss account that can carry either sign. This creates ambiguity in sign-convention validation. | Low |
| COA-06 | **`cf_category` is blank for many accounts** — Several accounts (e.g., `6100`, `6110`, `6120`, `6300`, `6310`, `6400`, `6410`, `6900`) have an empty `cf_category`. This is not an error per se but relevant if cash-flow statement preparation is in scope. | Low |

---

## 3. manual_adjustments.json

| # | JE | Finding | Severity |
|---|---|---------|----------|
| JE-001 | JE-001 | **Valid entry** — Debit `6100` $850,000; Credit `2120` $850,000. Balanced. Both accounts exist in COA. | — |
| JE-002 | JE-002 | **Unbalanced entry** — Debit `6300` $28,500; Credit `6310` $25,000. Difference = **$3,500**. Hard reject. | Critical |
| JE-003 | JE-003 | **FX revaluation — plausible but needs rate verification** — The entry credits `7310` $11,200 as an unrealised FX gain on EUR cash. The EUR period-end rate is 1.095. EUR cash balance is 825,400 EUR; at opening rate 1.071 that is $883,803; at period-end 1.095 that is $904,113; difference = $20,310 USD. The adjustment amount of $11,200 does not match this calculation, suggesting either a partial reval or an error in the source workbook. Should be quarantined for review. | Medium |
| JE-004 | JE-004 | **Valid entry** — Debit `6600` $45,000; Credit `1121` $45,000. Balanced. Both accounts exist. | — |
| JE-005 | JE-005 | **Unknown account `6315`** — Debit `6315` $18,500; Credit `6310` $18,500. Balanced arithmetically but `6315` does not exist in the COA. Must be quarantined/rejected. | High |
| JE-006 | JE-006 | **Valid entry** — Debit `6500` $215,000; Credit `1211` $215,000. Balanced. Both accounts exist. | — |
| JE-007 | JE-007 | **Valid entry** — Debit `8200` $38,000; Credit `1250` $38,000. Balanced. Both accounts exist. | — |
| JE-008 | JE-008 | **Same-account wash entry** — Both debit and credit lines use account `2170` (Intercompany Payable) for $320,000 each. Arithmetically balanced but net effect is zero. Likely a recording error or orphaned IC entry. The description says "Intercompany settlement — UK sub", flagging an intercompany context. Should be quarantined. | High |
| JE-009 | JE-009 | **Valid entry** — Debit `6400` $75,000; Credit `2120` $75,000. Balanced. Both accounts exist. | — |
| JE-010 | JE-010 | **Valid entry** — Debit `2210` $200,000; Credit `2140` $200,000. Balanced. Both accounts exist. | — |

---

## 4. fx_rates.csv

| # | Finding | Severity |
|---|---------|----------|
| FX-01 | **Missing GBP period_end rate** — The TB has a GBP cash row (412,300 GBP) that requires a period-end rate for balance sheet translation. Only `period_average` and `opening` rates exist for GBP; `period_end` is absent. This blocks accurate BS translation of GBP balances. | High |
| FX-02 | **Missing USD opening rate** — USD has `period_average` and `period_end` (both 1.0) but no `opening` row. Not functionally impactful (USD = functional currency) but technically incomplete. | Low |

---

## 5. prior_period_tb.csv

| # | Finding | Severity |
|---|---------|----------|
| PP-01 | **Account `6905` not in current COA** — `Sundry Operating Expenses` with debit $132,000 in the prior period has no matching entry in `chart_of_accounts.csv`. This is an orphan account that would fail COA mapping. | Low |
| PP-02 | **No P&L lines** — The prior period TB only contains balance sheet accounts (1xxx–3xxx), which is normal for a closing/opening balance file. However, `6905` above is a P&L account, which is inconsistent with this pattern. | Low |
| PP-03 | **Multi-currency cash rows** — Same pattern as current TB: EUR and GBP rows for `1110` are in local currency and need FX translation. | Medium |

---

## 6. Summary — Issues by Category

| Category | Count | Highest Severity |
|----------|-------|-----------------|
| Unbalanced journal entry | 1 (JE-002) | Critical |
| Unknown/missing account | 2 (JE-005 `6315`, TB `9999`) | High |
| Same-account wash/no-op entry | 1 (JE-008) | High |
| Intercompany flag | 1 (JE-008) | High |
| Missing FX rate | 1 (GBP period_end) | High |
| FX reval amount mismatch | 1 (JE-003) | Medium |
| Duplicate TB rows | 1 (account `6310`) | High |
| Header accounts in COA | 12 (all Header-type) | Medium |
| Orphan accounts (prior period) | 1 (`6905`) | Low |

---

## 7. Validation Rules Derived from Findings

1. Every journal entry line's `account` code must exist in the COA as a **non-Header** account.
2. Total debits must equal total credits within a tolerance of $0.01.
3. Any entry where a single account appears on both the debit and credit side must be quarantined (same-account check).
4. Any entry where the description or memo contains intercompany keywords (`intercompany`, `IC`, `UK sub`, etc.) must be flagged for human review.
5. Required fields on every JE: `id`, `description`, `date`, `source`, `lines` (non-empty).
6. Duplicate lines (same account, same debit, same credit, same memo) must be flagged.
7. FX revaluation entries should be noted for manual rate verification if they involve non-USD accounts.
