# AI Financial Adjustment Agent

An AI-assisted financial validation system that checks manual journal entries, detects accounting defects, and provides clear explanations for finance users.

The core accounting validation is **deterministic and rule-based**. AI is used only where it adds value — primarily for generating human-readable explanations. The AI does **not** calculate accounting values, validate account codes, or decide whether an entry should be accepted or rejected.

---

## Overview

Finance teams frequently create manual journal entries (JEs) for corrections, reclassifications, accruals, and period-end adjustments.

These entries can contain problems such as:

* Unbalanced debit and credit amounts
* Invalid or non-existent account codes
* Duplicate journal lines
* Same-account debit and credit wash entries
* Intercompany transactions requiring review
* Entries that conflict with normal account balances
* Zero-net-effect transactions

This project automatically validates these entries and assigns one of three statuses:

| Status        | Meaning                                                 |
| ------------- | ------------------------------------------------------- |
| ✅ ACCEPT      | All deterministic checks passed                         |
| ❌ REJECT      | A hard validation error was detected                    |
| ⚠️ QUARANTINE | Entry is mathematically valid but requires human review |

The system is designed around a **human-in-the-loop** approach. Suspicious entries are never automatically approved.

---

## Key Design Principle

### Less AI, More Deterministic Engineering

This project intentionally does **not** use an LLM for core accounting validation.

Accounting rules such as:

* Debit = Credit
* Account existence
* Account postability
* Duplicate detection
* Intercompany detection
* Normal-balance validation
* Zero-net wash detection

are implemented using Python and deterministic validation logic.

This makes the system:

* Reproducible
* Auditable
* Predictable
* Easier to test
* Safer for financial workflows

The same input produces the same validation result.

### Where AI Is Used

AI has a limited role in the application.

The LLM is used to convert already-computed validation results into a natural-language explanation that is easier for a finance user to understand.

The LLM receives:

* Journal entry ID
* Description
* Date
* Source
* Debit and credit totals
* Difference
* Validation errors
* Validation warnings
* Pre-decided status

The LLM does **not**:

* Calculate accounting amounts
* Look up account codes
* Decide the validation status
* Override validation rules
* Approve quarantined entries
* Modify journal entries

If an LLM is unavailable, the application automatically uses a deterministic explanation.

---

## Architecture

```text
                    ┌─────────────────────────┐
                    │      User / Finance     │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Upload COA + JEs      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Upload Pre-validation │
                    └────────────┬────────────┘
                                 │
                                 ▼
              ┌─────────────────────────────────────┐
              │      Deterministic Validation       │
              │                                     │
              │  • Required fields                  │
              │  • Debit / Credit balance           │
              │  • Account existence                │
              │  • Account postability              │
              │  • Duplicate lines                  │
              │  • Intercompany detection           │
              │  • Normal-balance checks             │
              │  • Zero-net wash detection          │
              └──────────────────┬──────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ ACCEPT / REJECT /       │
                    │ QUARANTINE              │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Optional AI Explanation │
                    │        + Fallback        │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │     Review & Export     │
                    └─────────────────────────┘
```

---

## Project Structure

```text
ai-financial-adjustment-agent/
│
├── app/
│   ├── agents/
│   │   ├── llm_provider.py
│   │   ├── explanation_agent.py
│   │   └── adjustment_agent.py
│   │
│   ├── models/
│   │   └── schemas.py
│   │
│   ├── services/
│   │   ├── coa_service.py
│   │   └── adjustment_service.py
│   │
│   ├── validators/
│   │   ├── field_validator.py
│   │   ├── balance_validator.py
│   │   ├── account_validator.py
│   │   ├── duplicate_validator.py
│   │   ├── intercompany_validator.py
│   │   ├── semantic_validator.py
│   │   └── fx_validator.py
│   │
│   ├── utils/
│   │   ├── upload_validator.py
│   │   └── output_writer.py
│   │
│   ├── main.py
│   └── streamlit_app.py
│
├── data/
│   ├── manual_adjustments.json
│   ├── chart_of_accounts.csv
│   ├── trial_balance.csv
│   ├── prior_period_tb.csv
│   └── fx_rates.csv
│
├── tests/
│   ├── conftest.py
│   ├── test_validators.py
│   ├── test_adjustment_service.py
│   ├── test_coa_service.py
│   ├── test_schemas.py
│   └── test_upload_validator.py
│
├── .env.example
├── DATA_FINDINGS.md
├── requirements.txt
└── README.md
```

---

## Validation Rules

### 1. Required Fields

Every journal entry must contain:

```text
id
description
date
source
lines
```

Missing required fields result in rejection.

### 2. Balance Validation

The system verifies:

```text
Total Debit == Total Credit
```

A tolerance of `$0.01` is supported.

Unbalanced entries are rejected.

### 3. Account Existence

Every account code is checked against the uploaded Chart of Accounts.

Unknown account codes result in rejection.

### 4. Account Postability

Header/roll-up accounts cannot be used for direct posting.

### 5. Duplicate Lines

Identical journal lines are flagged for human review.

### 6. Same-Account Debit and Credit

An account appearing on both sides of an entry is flagged as suspicious.

### 7. Intercompany Detection

The system checks descriptions, sources, memos, and known intercompany account codes for potential intercompany activity.

These entries are quarantined for review.

### 8. Normal-Balance Validation

The system identifies transactions that conflict with the account's expected normal balance.

### 9. Zero-Net Wash Detection

If the net impact on every account is zero, the entry is flagged for review.

---

## Human-in-the-Loop

The system intentionally separates automatic validation from human approval.

```text
ACCEPT
  ↓
Can proceed

REJECT
  ↓
Correct the journal entry
  ↓
Submit again

QUARANTINE
  ↓
Human controller review
  ↓
Manual approval required
```

A quarantined entry is never automatically approved.

---

## Dashboard

The project includes a Streamlit dashboard with a three-step workflow:

```text
① Upload Data
       ↓
② Validate
       ↓
③ Review Results
```

### Upload

Users can:

* Load the bundled demo dataset
* Upload their own Chart of Accounts
* Upload manual journal entries
* Optionally upload supporting datasets

### Validation

The dashboard displays processing progress for:

* File validation
* Account validation
* Debit/credit validation
* Semantic checks
* Explanation generation

### Results

The dashboard provides:

* Total entries
* Accepted entries
* Rejected entries
* Quarantined entries
* Error count
* Warning count
* Search
* Status filtering
* Individual entry inspection

---

## Entry Inspection

Each journal entry can be inspected through:

1. Overview
2. Journal Entry Lines
3. Account Validation
4. Balance Validation
5. Errors
6. Warnings
7. AI Explanation
8. Human Review

This provides transparency into why an entry received its status.

---

## Export

The dashboard provides downloadable results:

```text
adjustment_results.json
adjustment_summary.csv
```

The results contain the validation outcome, calculations, errors, warnings, account checks, explanations, and human-review information.

---

## Setup

### Requirements

* Python 3.10+
* pip

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

For deterministic operation without an LLM:

```env
LLM_PROVIDER=none
```

Optional OpenAI configuration:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-4o-mini
```

Optional Gemini configuration:

```env
LLM_PROVIDER=gemini
GOOGLE_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.0-flash
```

The application can run without an API key because deterministic explanations are available as a fallback.

---

## Run the Application

### Streamlit Dashboard

```bash
streamlit run app/streamlit_app.py
```

Then open:

```text
http://localhost:8501
```

### CLI

```bash
python -m app.main
```

Available options:

```text
--data-dir PATH
--output-dir PATH
--verbose
```

---

## Run Tests

```bash
python -m pytest tests/ -v
```

The test suite covers:

* Validators
* Adjustment service
* Chart of Accounts service
* Pydantic schemas
* Upload validation
* In-memory processing

---

## Example Result

```text
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ ID     ┃ Description              ┃ Status     ┃ Debit      ┃ Credit     ┃ Diff     ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━┩
│ JE-001 │ Accrue Q4 bonus pool     │ ACCEPT     │ 850,000.00 │ 850,000.00 │ 0.00     │
│ JE-002 │ Reclassify marketing     │ REJECT     │ 28,500.00  │ 25,000.00  │ 3,500.00 │
│ JE-003 │ FX revaluation           │ QUARANTINE │ 11,200.00  │ 11,200.00  │ 0.00     │
│ JE-004 │ Bad debt provision        │ ACCEPT     │ 45,000.00  │ 45,000.00  │ 0.00     │
│ JE-008 │ Intercompany settlement  │ QUARANTINE │ 320,000.00 │ 320,000.00 │ 0.00     │
└────────┴──────────────────────────┴────────────┴────────────┴────────────┴──────────┘
```

---

## Why This Approach?

Traditional LLM-based financial systems can introduce unnecessary uncertainty when they are used for deterministic accounting operations.

This project follows a different approach:

```text
                    Accounting Rules
                           │
                           ▼
                  Deterministic Python
                           │
                           ▼
                Reliable Validation Result
                           │
                           ▼
                     Optional AI
                           │
                           ▼
                 Human-readable Explanation
```

The important accounting decision is made by deterministic code.

AI is only an assistance layer.

This keeps the system **AI-assisted rather than AI-dependent**.

---

## Security & Data Handling

* API keys should be stored in `.env`.
* `.env` should never be committed to GitHub.
* `.env.example` contains only configuration placeholders.
* Uploaded data is processed in memory where possible.
* Temporary files are cleaned after use.
* Source files are not modified by the validation engine.

---

## Limitations

Current limitations include:

* Trial balance analysis is not part of the current validation scope.
* FX amount reconciliation is not independently calculated against balance/rate data.
* Intercompany detection is primarily keyword/account-code based.
* There is no persistent database.
* Legitimate reversal entries can still require human review.
* Streamlit accessibility has not been formally validated with assistive technologies.

---

## Development Philosophy

The project was built with the following principles:

### 1. Deterministic First

Accounting calculations and validation rules should be reproducible.

### 2. Minimal AI Dependency

The application should remain functional even when no AI API is configured.

### 3. Human Oversight

Suspicious accounting entries should be reviewed by humans rather than automatically approved.

### 4. Explainability

Every validation result should provide understandable reasons.

### 5. Auditability

The system preserves the input values, calculated totals, validation findings, and final status.

---

## AI Usage During Development

AI-assisted development tools were used during development for tasks such as code assistance, debugging, documentation, and project organization.

However, **AI was intentionally kept out of the core accounting decision-making process**.

The application does not ask an LLM to decide whether a journal entry balances or whether an account exists. Those decisions are handled directly by deterministic Python validators.

The runtime AI component is optional and is limited to generating natural-language explanations.

In short:

> **Less AI for decisions, more deterministic engineering for correctness.**

---

## License

This project was created as a prototype/take-home assignment for demonstrating software engineering, validation design, AI integration, and human-in-the-loop system design.
