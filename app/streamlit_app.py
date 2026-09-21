"""
AI Financial Adjustment Agent — Streamlit Dashboard (v3).

Three-step workflow:
  1 Upload  ->  2 Validate  ->  3 Review

What changed from v2 (UI only, backend calls are identical):
  * Files are checked as soon as they are uploaded, so the Validate button
    only enables when the run can succeed.
  * The results table is sortable (real numbers, not strings) and you click a
    row to open it. Falls back to a dropdown on older Streamlit versions.
  * One status filter instead of cards + a second row of "Filter" buttons.
  * Entry detail is split into tabs instead of eight stacked expanders.
  * All uploaded / model-generated text is HTML-escaped before it is rendered.
  * The AI explanation is rendered as Markdown, labelled as AI-generated.
  * Failed runs no longer leave a blank page.

sys.path is patched at import time so `app.*` imports resolve correctly
when Streamlit launches from any working directory.
"""

from __future__ import annotations

import csv as _csv
import html
import io
import json
import re
import sys
import tempfile
from pathlib import Path

# ── Project root on sys.path ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="AI Financial Adjustment Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.agents.explanation_agent import build_explanation_fn  # noqa: E402
from app.agents.llm_provider import LLMProvider  # noqa: E402
from app.models.schemas import EntryResult  # noqa: E402
from app.services.adjustment_service import AdjustmentService  # noqa: E402
from app.services.coa_service import CoAService  # noqa: E402
from app.utils.upload_validator import (  # noqa: E402
    validate_accounts_exist_in_coa,
    validate_adjustments_json,
    validate_coa_csv,
    validate_fx_csv,
    validate_tb_csv,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEMO_DATA_DIR = _PROJECT_ROOT / "data"

_STATUS_LABEL = {
    "ACCEPT": "Accepted",
    "REJECT": "Rejected",
    "QUARANTINE": "Quarantined",
}
_STATUS_ICON = {"ACCEPT": "✅", "REJECT": "❌", "QUARANTINE": "⚠️"}
_BALANCE_TOLERANCE = 0.005  # display-only; the backend decides the real status

# Session-state keys (unchanged from v2)
_K_RESULTS   = "results"
_K_PERIOD    = "period"
_K_FC        = "fc"
_K_GENERATED = "generated_at"
_K_JSON      = "json_bytes"
_K_CSV       = "csv_bytes"
_K_SOURCE    = "source"
_K_STEP      = "step"          # 1 | 3  (2 is shown only while processing)
_K_FILTER    = "filter_status"

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
# Palette
#   ink      #0b1220  page          panel   #111a2b  cards
#   line     #22304a  borders       text    #e6ebf5  body
#   muted    #9aa8c1  secondary     focus   #5b9dff  primary action
#   accept   #4cc38a  reject #ef6b6b  quarantine #f0b34a
# Type: IBM Plex Sans (tabular figures on every number).

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
    --bg:#f6f8fb; --surface:#ffffff; --surface2:#f8fafc;
    --line:#e3e8ef; --text:#172033; --muted:#697586;
    --navy:#172337; --blue:#1976d2; --blue-soft:#eaf3ff;
    --accept:#16a36a; --accept-bg:#eaf8f2;
    --reject:#dc4c64; --reject-bg:#fff0f2;
    --quar:#d58a16; --quar-bg:#fff7e7;
    --shadow:0 1px 2px rgba(16,24,40,.04),0 4px 16px rgba(16,24,40,.04);
}
html,body,[class*="css"]{font-family:'Inter','Segoe UI',system-ui,sans-serif;color:var(--text);}
.stApp{background:var(--bg);}
.block-container{padding-top:1.25rem;padding-bottom:3rem;max-width:1400px;}

[data-testid="stSidebar"]{background:#fff;border-right:1px solid var(--line);}
[data-testid="stSidebar"]>div:first-child{padding-top:1rem;}
[data-testid="stSidebar"] hr{border-color:var(--line)!important;}
[data-testid="stSidebar"] .stRadio label{padding:7px 10px;border-radius:7px;}
[data-testid="stSidebar"] .stRadio label:hover{background:var(--blue-soft);}

.topbar{background:var(--navy);color:#fff;border-radius:10px;padding:11px 18px;
display:flex;align-items:center;justify-content:space-between;box-shadow:var(--shadow);margin-bottom:18px;}
.brand{display:flex;align-items:center;gap:10px;}
.brand-mark{width:30px;height:30px;border-radius:7px;display:inline-flex;align-items:center;
justify-content:center;background:#fff;color:var(--blue);font-weight:800;font-size:14px;}
.brand-name{font-size:15px;font-weight:700;}
.brand-sub{font-size:11px;color:#b8c3d4;}
.page-title{font-size:27px;line-height:1.15;font-weight:700;color:var(--text);margin:2px 0 3px;}
.page-subtitle{color:var(--muted);font-size:13px;margin:0 0 8px;}
.section-title{font-size:16px;font-weight:650;color:var(--text);margin:1.25rem 0 .45rem;}
.section-hint{font-size:12.5px;color:var(--muted);margin:-.2rem 0 .7rem;}

div[data-testid="stVerticalBlockBorderWrapper"]{background:var(--surface);
border-color:var(--line)!important;border-radius:9px;box-shadow:var(--shadow);}

.workflow{background:var(--surface);border:1px solid var(--line);border-radius:9px;
padding:11px 16px;box-shadow:var(--shadow);margin:12px 0 18px;}
.stepper{display:flex;align-items:center;gap:9px;flex-wrap:wrap;}
.step{display:flex;align-items:center;gap:7px;color:#8a94a6;font-size:12.5px;font-weight:500;}
.step-num{width:23px;height:23px;border-radius:50%;display:inline-flex;align-items:center;
justify-content:center;border:1px solid #ccd5e1;color:#778397;background:#fff;font-size:11.5px;font-weight:700;}
.step.active{color:var(--blue);}
.step.active .step-num{background:var(--blue);border-color:var(--blue);color:#fff;}
.step.done{color:var(--accept);}
.step.done .step-num{background:var(--accept-bg);border-color:#8bd8b6;color:var(--accept);}
.step-line{height:1px;width:44px;background:#d9e0e8;}

.kpi{background:var(--surface);border:1px solid var(--line);border-radius:9px;padding:15px 17px;
min-height:92px;box-shadow:var(--shadow);}
.kpi-label{font-size:12px;color:var(--muted);margin-bottom:8px;}
.kpi-value{font-size:27px;font-weight:700;color:var(--text);line-height:1;}
.kpi-sub{font-size:11.5px;color:var(--muted);margin-top:7px;}
.kpi.accept .kpi-value{color:var(--accept);}
.kpi.reject .kpi-value{color:var(--reject);}
.kpi.quar .kpi-value{color:var(--quar);}

.outcome{display:flex;height:9px;border-radius:5px;overflow:hidden;background:#edf1f5;margin:16px 0 7px;}
.outcome>div{height:100%;}
.outcome .a{background:var(--accept);}.outcome .r{background:var(--reject);}.outcome .q{background:var(--quar);}
.outcome-legend{display:flex;gap:18px;font-size:12px;color:var(--muted);flex-wrap:wrap;}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;}

.attention{background:var(--quar-bg);border:1px solid #f1d18e;border-left:4px solid var(--quar);
border-radius:8px;padding:11px 14px;margin:14px 0 4px;color:#7b5717;font-size:13px;}
.allclear{background:var(--accept-bg);border:1px solid #a9dfc6;border-left:4px solid var(--accept);
border-radius:8px;padding:11px 14px;margin:14px 0 4px;color:#126b48;font-size:13px;}

.meta{display:flex;gap:20px;font-size:12px;color:var(--muted);flex-wrap:wrap;margin:5px 0 7px;}
.meta b{color:var(--text);font-weight:600;}
.chip{display:inline-block;font-size:11.5px;padding:3px 9px;border-radius:999px;margin:2px 5px 2px 0;}
.chip.ok{background:var(--accept-bg);color:#08754a;border:1px solid #a9dfc6;}
.chip.bad{background:var(--reject-bg);color:#a92e43;border:1px solid #f0b5c0;}
.chip.warn{background:var(--quar-bg);color:#875c0d;border:1px solid #f1d18e;}
.chip.info{background:#f1f4f8;color:#667085;border:1px solid #dce2ea;}
.file-msg{font-size:12px;color:#b4233b;padding:2px 0;}

.entry-head{border-radius:9px;padding:14px 17px;margin:8px 0 12px;border:1px solid;}
.entry-head.ACCEPT{background:var(--accept-bg);border-color:#a9dfc6;}
.entry-head.REJECT{background:var(--reject-bg);border-color:#f0b5c0;}
.entry-head.QUARANTINE{background:var(--quar-bg);border-color:#f1d18e;}
.entry-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;}
.entry-id{font-size:18px;font-weight:700;color:var(--text);}
.entry-desc{font-size:13px;color:var(--muted);margin-left:9px;}
.entry-meta{display:flex;gap:20px;margin-top:7px;font-size:12px;color:var(--muted);flex-wrap:wrap;}
.badge{padding:3px 10px;border-radius:999px;font-size:11.5px;font-weight:650;border:1px solid;}
.badge.ACCEPT{background:var(--accept-bg);color:#08754a;border-color:#8bd8b6;}
.badge.REJECT{background:var(--reject-bg);color:#a92e43;border-color:#ef9baa;}
.badge.QUARANTINE{background:var(--quar-bg);color:#875c0d;border-color:#e8bf70;}

.issue{border-radius:8px;padding:10px 13px;margin-bottom:8px;border:1px solid;border-left-width:4px;}
.issue.error{background:var(--reject-bg);border-color:#f0b5c0;border-left-color:var(--reject);}
.issue.warning{background:var(--quar-bg);border-color:#f1d18e;border-left-color:var(--quar);}
.issue-title{font-weight:650;font-size:13px;margin-bottom:2px;color:var(--text);}
.issue-body{font-size:12.5px;color:#475467;}
.issue-action{font-size:11.5px;color:var(--muted);margin-top:5px;}

.review{background:var(--quar-bg);border:1px solid #f1d18e;border-radius:9px;padding:14px 16px;}
.review-title{color:#875c0d;font-weight:650;font-size:13.5px;margin-bottom:7px;}
.review-item{color:#76530f;font-size:12.5px;padding:2px 0;}
.review-foot{margin-top:9px;font-size:11.5px;color:#94702b;}

.bal-row{display:flex;align-items:center;gap:11px;margin:8px 0;font-size:12.5px;color:var(--muted);}
.bal-label{width:52px}.bal-track{flex:1;height:8px;background:#edf1f5;border-radius:4px;overflow:hidden;}
.bal-fill{height:100%;border-radius:4px;background:var(--blue);}.bal-fill.credit{background:#7b6ee8;}
.bal-amt{width:145px;text-align:right;color:var(--text);font-variant-numeric:tabular-nums;}

div[data-testid="metric-container"]{background:var(--surface);border:1px solid var(--line);
border-radius:8px;padding:10px 13px;box-shadow:none;}
div[data-testid="metric-container"] label{color:var(--muted);font-size:11.5px;}
div[data-testid="metric-container"] [data-testid="stMetricValue"]{font-size:21px;font-weight:700;}
button[kind="primary"]{background:#1976d2!important;border-color:#1976d2!important;}
button[kind="primary"]:hover{background:#1565c0!important;border-color:#1565c0!important;}
.stButton>button,.stDownloadButton>button{border-radius:7px!important;font-weight:600!important;}
button[role="tab"]{font-size:12.5px;}
hr{border-color:var(--line)!important;margin:1rem 0!important;}
[data-testid="stFileUploaderDropzone"]{border:1px dashed #b9c5d4!important;border-radius:8px!important;background:#fbfcfe!important;}
[data-testid="stFileUploaderDropzone"]:hover{border-color:var(--blue)!important;background:#f6faff!important;}
.stDataFrame{border:1px solid var(--line);border-radius:8px;overflow:hidden;}
</style>
"""



# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _e(value) -> str:
    """HTML-escape anything that ends up inside unsafe_allow_html markup."""
    return html.escape("" if value is None else str(value), quote=True)


def _stretch(fn, *args, **kwargs):
    """
    Call a Streamlit widget at full width on both old and new Streamlit.
    New releases use width="stretch"; older ones use use_container_width=True.
    """
    try:
        return fn(*args, width="stretch", **kwargs)
    except (TypeError, st.errors.StreamlitAPIException):
        return fn(*args, use_container_width=True, **kwargs)


def _money(value: float, currency: str = "") -> str:
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{float(value):,.2f}"


def _is_balanced(diff: float) -> bool:
    return abs(float(diff)) < _BALANCE_TOLERANCE


# ---------------------------------------------------------------------------
# Serialisation helpers (unchanged behaviour)
# ---------------------------------------------------------------------------

def _result_to_dict(r: EntryResult) -> dict:
    # Floats are for display only. The backend keeps exact values.
    return {
        "entry_id": r.entry_id,
        "description": r.description,
        "date": r.date,
        "source": r.source,
        "status": r.status.value,
        "total_debit": float(r.total_debit),
        "total_credit": float(r.total_credit),
        "difference": float(r.difference),
        "error_count": r.error_count,
        "warning_count": r.warning_count,
        "errors": r.errors,
        "warnings": r.warnings,
        "account_checks": [
            {
                "account": c.account,
                "exists_in_coa": c.exists_in_coa,
                "is_postable": c.is_postable,
                "account_type": c.account_type,
                "normal_balance": c.normal_balance,
                "issue": c.issue,
            }
            for c in r.account_checks
        ],
        "explanation": r.explanation,
        "human_review_required": r.human_review_required,
        "review_reason": r.review_reason,
        "original_lines": [
            {
                "account": line.account,
                "debit": float(line.debit),
                "credit": float(line.credit),
                "memo": line.memo,
            }
            for line in r.original_lines
        ],
    }


def _batch_to_bytes(batch) -> tuple[bytes, bytes]:
    from app.utils.output_writer import _result_to_dict as _r2d  # type: ignore[attr-defined]

    payload = {
        "period": batch.period,
        "functional_currency": batch.functional_currency,
        "generated_at": batch.generated_at.isoformat(),
        "summary": {
            "total": batch.total_entries,
            "accepted": len(batch.accepted),
            "rejected": len(batch.rejected),
            "quarantined": len(batch.quarantined),
            "total_errors": batch.total_errors,
            "total_warnings": batch.total_warnings,
        },
        "results": [_r2d(r) for r in batch.results],
    }
    json_bytes = json.dumps(
        payload,
        indent=2,
        default=lambda o: float(o) if hasattr(o, "__float__") else str(o),
    ).encode("utf-8")

    rows = [r.to_summary_row() for r in batch.results]
    buf = io.StringIO()
    if rows:
        w = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    csv_bytes = buf.getvalue().encode("utf-8")

    return json_bytes, csv_bytes


def _store_batch(batch, source: str) -> None:
    json_bytes, csv_bytes = _batch_to_bytes(batch)
    st.session_state[_K_RESULTS]   = [_result_to_dict(r) for r in batch.results]
    st.session_state[_K_PERIOD]    = batch.period
    st.session_state[_K_FC]        = batch.functional_currency
    st.session_state[_K_GENERATED] = batch.generated_at.isoformat()
    st.session_state[_K_JSON]      = json_bytes
    st.session_state[_K_CSV]       = csv_bytes
    st.session_state[_K_SOURCE]    = source
    st.session_state[_K_STEP]      = 3


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def _run_with_steps(coa_source, adj_source, source_label: str) -> bool:
    """
    Run the full pipeline. Each line shown below is a real phase, not a timer.

    coa_source: Path | bytes
    adj_source: Path | dict
    Returns True on success. On failure the error is shown and the user stays
    on the upload step with their files still in place.
    """
    tmp_path: Path | None = None

    with st.status("Validating adjustments…", expanded=True) as status:
        try:
            st.write("Reading files")
            if isinstance(coa_source, bytes):
                with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
                    f.write(coa_source)
                    tmp_path = Path(f.name)
                coa_path = tmp_path
            else:
                coa_path = coa_source

            adj_data = adj_source if isinstance(adj_source, dict) else json.loads(
                adj_source.read_bytes()
            )

            st.write("Loading chart of accounts")
            coa = CoAService(coa_path)

            st.write("Connecting the explanation model")
            provider = LLMProvider.from_env()
            explanation_fn = build_explanation_fn(provider)
            service = AdjustmentService(coa=coa, data_dir=_DEMO_DATA_DIR)

            st.write("Checking accounts, balances and business rules, then writing explanations")
            if isinstance(adj_source, dict):
                batch = service.process_batch_from_data(
                    raw_data=adj_data, explanation_fn=explanation_fn
                )
            else:
                batch = service.process_batch(explanation_fn=explanation_fn)

            st.write("Preparing results")
            _store_batch(batch, source=source_label)
            status.update(label="Validation complete", state="complete", expanded=False)
            return True

        except Exception as exc:  # noqa: BLE001 - surface any backend failure to the user
            status.update(label="Validation failed", state="error", expanded=True)
            st.error(
                f"**Validation could not finish.** {exc}\n\n"
                "Your files are still loaded, so you can fix the problem and run it again. "
                "If the message mentions an API key or model provider, check your `.env` file."
            )
            return False
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Header + stepper
# ---------------------------------------------------------------------------

def _header() -> None:
    st.markdown(
        """
        <div class="topbar">
            <div class="brand">
                <span class="brand-mark">FA</span>
                <span class="brand-name">FinAudit AI</span>
                <span class="brand-sub">Financial Adjustment Agent</span>
            </div>
            <div style="font-size:12px;color:#c9d3e2;">Journal Entry Validation</div>
        </div>
        <div class="page-title">Financial Adjustment Audit</div>
        <div class="page-subtitle">
            Validate manual journal entries, identify accounting issues,
            and review AI-assisted findings before posting.
        </div>
        """,
        unsafe_allow_html=True,
    )


def _stepper_html(step: int) -> str:
    labels = ["Upload files", "Validate", "Review results"]
    parts: list[str] = []
    for i, label in enumerate(labels, 1):
        cls = "done" if i < step else "active" if i == step else ""
        mark = "✓" if i < step else str(i)
        parts.append(
            f"<div class='step {cls}'><span class='step-num'>{mark}</span>{_e(label)}</div>"
        )
        if i < len(labels):
            parts.append("<div class='step-line'></div>")
    return "<div class='stepper'>" + "".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# Step 1 — Upload
# ---------------------------------------------------------------------------

def _chip(kind: str, text: str) -> str:
    return f"<span class='chip {kind}'>{_e(text)}</span>"


def _optional_chip(uploaded, validator) -> str:
    if uploaded is None:
        return ""
    errs, _ = validator(uploaded.getvalue(), uploaded.name)
    if errs:
        return _chip("warn", f"{uploaded.name}: {errs[0]}")
    return _chip("ok", f"{uploaded.name} looks good")


def _step_upload() -> tuple[str | None, dict]:
    """
    Render the upload step.
    Returns (action, payload) where action is None, "upload" or "demo".
    """
    st.markdown("<div class='section-title'>Accounting data</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='section-hint'>Upload the files you want to validate. Required files are checked immediately.</div>",
        unsafe_allow_html=True,
    )

    col_req, col_opt = st.columns([1, 1], gap="large")

    coa_file = adj_file = None
    coa_df = adj_data = None
    file_errors: list[str] = []
    notices: list[str] = []

    with col_req:
        with st.container(border=True):
            st.markdown("<div style='font-size:13px;font-weight:650;color:#172033;margin-bottom:8px;'>Required files</div>", unsafe_allow_html=True)
            coa_file = st.file_uploader(
                "Chart of accounts (CSV)",
                type=["csv"],
                key="upload_coa",
                help="Columns: account_code, account_name, account_type, normal_balance",
            )
            if coa_file is not None:
                errs, coa_df = validate_coa_csv(coa_file.getvalue(), coa_file.name)
                if errs:
                    file_errors.extend(errs)
                    st.markdown(_chip("bad", "Chart of accounts needs attention"), unsafe_allow_html=True)
                    for m in errs:
                        st.markdown(f"<div class='file-msg'>• {_e(m)}</div>", unsafe_allow_html=True)
                else:
                    n = len(coa_df) if coa_df is not None else 0
                    st.markdown(_chip("ok", f"{n} accounts loaded"), unsafe_allow_html=True)

            adj_file = st.file_uploader(
                "Manual adjustments (JSON)",
                type=["json"],
                key="upload_adj",
                help='Needs a top-level "entries" array',
            )
            if adj_file is not None:
                errs, adj_data = validate_adjustments_json(adj_file.getvalue(), adj_file.name)
                if errs:
                    file_errors.extend(errs)
                    st.markdown(_chip("bad", "Adjustments file needs attention"), unsafe_allow_html=True)
                    for m in errs:
                        st.markdown(f"<div class='file-msg'>• {_e(m)}</div>", unsafe_allow_html=True)
                else:
                    n = len(adj_data.get("entries", [])) if isinstance(adj_data, dict) else 0
                    st.markdown(_chip("ok", f"{n} journal entries found"), unsafe_allow_html=True)

    with col_opt:
        with st.container(border=True):
            st.markdown("<div style='font-size:13px;font-weight:650;color:#172033;margin-bottom:8px;'>Supporting data</div>", unsafe_allow_html=True)
            st.caption("Accepted now and kept for future analysis. They do not change today's results.")
            tb = st.file_uploader(
                "Trial balance (CSV)", type=["csv"], key="upload_tb",
                help="Columns: account_code, account_name, debit, credit",
            )
            st.markdown(
                _optional_chip(tb, lambda b, n: validate_tb_csv(b, n, "Trial Balance")),
                unsafe_allow_html=True,
            )
            prior = st.file_uploader(
                "Prior-period trial balance (CSV)", type=["csv"], key="upload_prior",
                help="Same format as the trial balance",
            )
            st.markdown(
                _optional_chip(prior, lambda b, n: validate_tb_csv(b, n, "Prior Period TB")),
                unsafe_allow_html=True,
            )
            fx = st.file_uploader(
                "FX rates (CSV)", type=["csv"], key="upload_fx",
                help="Columns: currency, rate_type, rate",
            )
            st.markdown(_optional_chip(fx, validate_fx_csv), unsafe_allow_html=True)

    # Cross-check accounts in the entries against the chart of accounts
    if coa_df is not None and adj_data is not None and not file_errors:
        notices = list(validate_accounts_exist_in_coa(adj_data, coa_df))
        if notices:
            with st.expander(f"Heads-up: {len(notices)} account notice(s) before you run", expanded=False):
                for n in notices:
                    st.markdown(f"- {n}")
                st.caption("These entries will still be processed and flagged in the results.")

    ready = coa_file is not None and adj_file is not None and not file_errors

    st.markdown("<br>", unsafe_allow_html=True)
    b1, b2, hint = st.columns([1.2, 1, 3])
    validate_clicked = _stretch(
        b1.button, "Validate adjustments", type="primary", key="btn_validate", disabled=not ready
    )
    demo_clicked = _stretch(
        b2.button, "Try demo data", key="btn_demo",
        help="Runs the bundled 2024-Q4 sample dataset",
    )
    if not ready:
        if file_errors:
            hint.caption("Fix the issues above to continue.")
        else:
            missing = [
                name for name, f in (("chart of accounts", coa_file), ("adjustments file", adj_file))
                if f is None
            ]
            hint.caption("Still needed: " + " and ".join(missing) + ".")

    if demo_clicked:
        return "demo", {}
    if validate_clicked and ready:
        return "upload", {"coa_bytes": coa_file.getvalue(), "adj_data": adj_data}
    return None, {}


# ---------------------------------------------------------------------------
# Step 3 — Summary
# ---------------------------------------------------------------------------

def _summary(results: list[dict]) -> None:
    total = len(results)
    n_acc = sum(1 for r in results if r["status"] == "ACCEPT")
    n_rej = sum(1 for r in results if r["status"] == "REJECT")
    n_qua = sum(1 for r in results if r["status"] == "QUARANTINE")
    n_err = sum(r["error_count"] for r in results)
    n_wrn = sum(r["warning_count"] for r in results)
    n_hum = sum(1 for r in results if r["human_review_required"])

    cards = [
        ("Entries checked", total, "", f"{n_err} errors, {n_wrn} warnings"),
        ("Accepted", n_acc, "accept", "Ready to post"),
        ("Rejected", n_rej, "reject", "Fix and resubmit"),
        ("Quarantined", n_qua, "quar", "Needs a person to review"),
    ]
    cols = st.columns(4)
    for col, (label, value, cls, sub) in zip(cols, cards):
        col.markdown(
            f"<div class='kpi {cls}'><div class='kpi-label'>{_e(label)}</div>"
            f"<div class='kpi-value'>{value}</div><div class='kpi-sub'>{_e(sub)}</div></div>",
            unsafe_allow_html=True,
        )

    # Outcome bar: proportion of entries by result
    if total:
        segs = "".join(
            f"<div class='{cls}' style='width:{cnt / total * 100:.2f}%' "
            f"title='{_e(label)}: {cnt}'></div>"
            for cls, cnt, label in (("a", n_acc, "Accepted"), ("r", n_rej, "Rejected"), ("q", n_qua, "Quarantined"))
            if cnt
        )
        st.markdown(
            f"<div class='outcome' role='img' aria-label='{n_acc} accepted, {n_rej} rejected, "
            f"{n_qua} quarantined'>{segs}</div>"
            "<div class='outcome-legend'>"
            f"<span><span class='dot' style='background:var(--accept)'></span>{n_acc} accepted</span>"
            f"<span><span class='dot' style='background:var(--reject)'></span>{n_rej} rejected</span>"
            f"<span><span class='dot' style='background:var(--quar)'></span>{n_qua} quarantined</span>"
            "</div>",
            unsafe_allow_html=True,
        )

    if n_rej or n_qua:
        parts = []
        if n_rej:
            parts.append(f"{n_rej} rejected")
        if n_qua:
            parts.append(f"{n_qua} quarantined")
        review = f" {n_hum} need human sign-off." if n_hum else ""
        st.markdown(
            f"<div class='attention'><b>{' and '.join(parts)}.</b>{review} "
            "Use the filter below to see just those entries.</div>",
            unsafe_allow_html=True,
        )
    elif total:
        st.markdown(
            "<div class='allclear'><b>All entries passed.</b> Nothing needs review.</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Step 3 — Table
# ---------------------------------------------------------------------------

def _results_table(results: list[dict], fc: str) -> dict | None:
    """Show the filterable table. Returns the selected result dict, or None."""
    st.markdown("<div class='section-title'>Journal entries</div>", unsafe_allow_html=True)

    counts = {
        "ALL": len(results),
        "ACCEPT": sum(1 for r in results if r["status"] == "ACCEPT"),
        "REJECT": sum(1 for r in results if r["status"] == "REJECT"),
        "QUARANTINE": sum(1 for r in results if r["status"] == "QUARANTINE"),
    }
    st.session_state.setdefault(_K_FILTER, "ALL")

    c_search, c_filter = st.columns([2, 3])
    query = c_search.text_input(
        "Search entries",
        key="search_box",
        placeholder="Search by ID or description",
        label_visibility="collapsed",
    )
    status = c_filter.radio(
        "Show",
        options=["ALL", "ACCEPT", "REJECT", "QUARANTINE"],
        format_func=lambda k: (
            f"All ({counts['ALL']})" if k == "ALL"
            else f"{_STATUS_ICON[k]} {_STATUS_LABEL[k]} ({counts[k]})"
        ),
        horizontal=True,
        key=_K_FILTER,
        label_visibility="collapsed",
    )

    filtered = results
    if status != "ALL":
        filtered = [r for r in filtered if r["status"] == status]
    q = query.strip().lower()
    if q:
        filtered = [
            r for r in filtered
            if q in r["entry_id"].lower() or q in (r["description"] or "").lower()
        ]

    if not filtered:
        st.info("No entries match. Clear the search or pick a different status.")
        return None

    df = pd.DataFrame(
        [
            {
                "ID": r["entry_id"],
                "Description": r["description"],
                "Status": f"{_STATUS_ICON[r['status']]} {_STATUS_LABEL[r['status']]}",
                "Debit": r["total_debit"],
                "Credit": r["total_credit"],
                "Difference": r["difference"],
                "Errors": r["error_count"] or None,
                "Warnings": r["warning_count"] or None,
                "Review": "🔍 Yes" if r["human_review_required"] else "",
            }
            for r in filtered
        ]
    )
    cur = f" ({fc})" if fc else ""
    config = {
        "Debit": st.column_config.NumberColumn(f"Debit{cur}", format="%.2f"),
        "Credit": st.column_config.NumberColumn(f"Credit{cur}", format="%.2f"),
        "Difference": st.column_config.NumberColumn(f"Difference{cur}", format="%.2f"),
        "Errors": st.column_config.NumberColumn("Errors", format="%d"),
        "Warnings": st.column_config.NumberColumn("Warnings", format="%d"),
        "Description": st.column_config.TextColumn("Description", width="large"),
    }

    # Changing the filter or search changes the key, which clears any old selection
    table_key = f"tbl_{status}_{q}"

    try:
        event = _stretch(
            st.dataframe,
            df,
            hide_index=True,
            column_config=config,
            on_select="rerun",
            selection_mode="single-row",
            key=table_key,
        )
        rows = (event or {}).get("selection", {}).get("rows", []) if hasattr(event, "get") else []
        if rows and rows[0] < len(filtered):
            return filtered[rows[0]]
        st.caption("Click a row to see its full validation details.")
        return None
    except TypeError:
        # Older Streamlit: no row selection. Show the table and offer a dropdown.
        _stretch(st.dataframe, df, hide_index=True, column_config=config)
        choice = st.selectbox(
            "Open an entry",
            options=["Choose an entry"] + [r["entry_id"] for r in filtered],
            key="entry_select",
        )
        if choice == "Choose an entry":
            return None
        return next((r for r in filtered if r["entry_id"] == choice), None)


# ---------------------------------------------------------------------------
# Step 3 — Entry detail
# ---------------------------------------------------------------------------

def _balance_bars(debit: float, credit: float, fc: str) -> str:
    top = max(debit, credit, 0.01)
    return (
        "<div class='bal-row'><span class='bal-label'>Debit</span>"
        f"<div class='bal-track'><div class='bal-fill' style='width:{debit / top * 100:.1f}%'></div></div>"
        f"<span class='bal-amt'>{_e(_money(debit, fc))}</span></div>"
        "<div class='bal-row'><span class='bal-label'>Credit</span>"
        f"<div class='bal-track'><div class='bal-fill credit' style='width:{credit / top * 100:.1f}%'></div></div>"
        f"<span class='bal-amt'>{_e(_money(credit, fc))}</span></div>"
    )


def _tab_overview(r: dict, fc: str) -> None:
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total debit", _money(r["total_debit"], fc))
    m2.metric("Total credit", _money(r["total_credit"], fc))
    m3.metric("Difference", _money(r["difference"], fc))
    m4.metric("Errors", r["error_count"])
    m5.metric("Warnings", r["warning_count"])

    st.markdown(_balance_bars(r["total_debit"], r["total_credit"], fc), unsafe_allow_html=True)

    if _is_balanced(r["difference"]):
        st.success("Balanced. Total debits equal total credits.")
    else:
        st.error(
            f"Out of balance by {_money(r['difference'], fc)}. "
            "Correct the entry so debits equal credits before posting."
        )


def _tab_lines(r: dict, fc: str) -> None:
    lines = r["original_lines"]
    if not lines:
        st.caption("No lines available for this entry.")
        return

    checks = {c["account"]: c for c in r["account_checks"]}

    def coa_status(account: str) -> str:
        c = checks.get(account)
        if c is None:
            return "—"
        if not c["exists_in_coa"]:
            return "❌ Not in chart of accounts"
        if not c["is_postable"]:
            return "❌ Not postable"
        if c["issue"]:
            return "⚠️ See Accounts tab"
        return "✅ OK"

    rows = [
        {
            "Account": ln["account"],
            "Debit": ln["debit"] if float(ln["debit"]) > 0 else None,
            "Credit": ln["credit"] if float(ln["credit"]) > 0 else None,
            "Chart of accounts": coa_status(ln["account"]),
            "Memo": ln["memo"] or "",
        }
        for ln in lines
    ]
    rows.append(
        {
            "Account": "Total",
            "Debit": r["total_debit"],
            "Credit": r["total_credit"],
            "Chart of accounts": "",
            "Memo": "",
        }
    )
    cur = f" ({fc})" if fc else ""
    _stretch(
        st.dataframe,
        pd.DataFrame(rows),
        hide_index=True,
        column_config={
            "Debit": st.column_config.NumberColumn(f"Debit{cur}", format="%.2f"),
            "Credit": st.column_config.NumberColumn(f"Credit{cur}", format="%.2f"),
        },
    )


def _tab_accounts(r: dict) -> None:
    if not r["account_checks"]:
        st.caption("No account checks. This entry failed before accounts were checked.")
        return
    adf = pd.DataFrame(r["account_checks"])
    adf["exists_in_coa"] = adf["exists_in_coa"].map({True: "✅ Yes", False: "❌ No"})
    adf["is_postable"] = adf["is_postable"].map({True: "✅ Yes", False: "❌ No"})
    adf.columns = ["Account", "In chart?", "Postable?", "Type", "Normal balance", "Issue"]
    _stretch(st.dataframe, adf.fillna("").astype(str), hide_index=True)


def _tab_issues(r: dict) -> None:
    if not r["errors"] and not r["warnings"]:
        st.success("No errors or warnings for this entry.")
        return

    for err in r["errors"]:
        hint = ""
        m = re.search(r"account\s+'([^']+)'", err, re.IGNORECASE)
        if m:
            hint = f"<div class='issue-action'>Affected account: {_e(m.group(1))}</div>"
        st.markdown(
            "<div class='issue error'>"
            "<div class='issue-title'>🔴 Error</div>"
            f"<div class='issue-body'>{_e(err)}</div>{hint}"
            "<div class='issue-action'>Correct the entry and resubmit. "
            "It can't be posted as it is.</div></div>",
            unsafe_allow_html=True,
        )

    action = (
        "A person must review this before posting."
        if r["human_review_required"]
        else "Check that this is intentional before posting."
    )
    for warn in r["warnings"]:
        st.markdown(
            "<div class='issue warning'>"
            "<div class='issue-title'>🟡 Warning</div>"
            f"<div class='issue-body'>{_e(warn)}</div>"
            f"<div class='issue-action'>{_e(action)}</div></div>",
            unsafe_allow_html=True,
        )


def _tab_explanation(r: dict) -> None:
    expl = (r.get("explanation") or "").strip()
    if not expl:
        st.caption("No explanation was generated for this entry.")
        return
    with st.container(border=True):
        st.markdown(expl)  # Markdown, not raw HTML, so model output can't inject markup
    st.caption("Written by an AI model from the validation results. Check it against the Issues tab.")


def _tab_review(r: dict) -> None:
    if not r["human_review_required"]:
        st.success("No human review needed for this entry.")
        return

    items = ""
    for line in (r.get("review_reason") or "").split("\n"):
        stripped = line.lstrip("•").strip()
        if stripped and not stripped.startswith(("Entry ", "Desc", "Source", "Suggested", "Issues")):
            items += f"<div class='review-item'>• {_e(stripped)}</div>"

    st.markdown(
        "<div class='review'><div class='review-title'>⚠️ Human review required</div>"
        f"{items}"
        "<div class='review-foot'>Don't post this entry until the financial controller "
        "has reviewed and signed it off. Don't auto-approve.</div></div>",
        unsafe_allow_html=True,
    )


def _entry_detail(r: dict, fc: str) -> None:
    status = r["status"]
    st.markdown(
        f"<div class='entry-head {status}'>"
        "<div class='entry-top'><div>"
        f"<span class='entry-id'>{_STATUS_ICON.get(status, '')} {_e(r['entry_id'])}</span>"
        f"<span class='entry-desc'>{_e(r['description'])}</span></div>"
        f"<span class='badge {status}'>{_e(_STATUS_LABEL.get(status, status))}</span></div>"
        f"<div class='entry-meta'><span>📅 {_e(r['date'])}</span><span>📁 {_e(r['source'])}</span></div>"
        "</div>",
        unsafe_allow_html=True,
    )

    n_issues = r["error_count"] + r["warning_count"]
    tabs = st.tabs(
        [
            "Overview",
            "Lines",
            "Accounts",
            f"Issues ({n_issues})" if n_issues else "Issues",
            "AI explanation",
            "⚠️ Review" if r["human_review_required"] else "Review",
        ]
    )
    with tabs[0]:
        _tab_overview(r, fc)
    with tabs[1]:
        _tab_lines(r, fc)
    with tabs[2]:
        _tab_accounts(r)
    with tabs[3]:
        _tab_issues(r)
    with tabs[4]:
        _tab_explanation(r)
    with tabs[5]:
        _tab_review(r)


# ---------------------------------------------------------------------------
# Step 3 — Page
# ---------------------------------------------------------------------------

def _step_results() -> None:
    results = st.session_state.get(_K_RESULTS, [])
    period = st.session_state.get(_K_PERIOD, "—")
    fc = st.session_state.get(_K_FC, "") or ""
    source = "Demo data" if st.session_state.get(_K_SOURCE) == "demo" else "Uploaded files"
    generated = (st.session_state.get(_K_GENERATED) or "")[:19].replace("T", " ")

    # Action row: new run + exports live together at the top
    a1, a2, a3, _ = st.columns([1.1, 1.3, 1.3, 2.5])
    if _stretch(a1.button, "← New validation", key="btn_reset"):
        for k in (_K_RESULTS, _K_JSON, _K_CSV, _K_FILTER, "search_box", "entry_select"):
            st.session_state.pop(k, None)
        st.session_state[_K_STEP] = 1
        st.rerun()

    if st.session_state.get(_K_JSON):
        _stretch(
            a2.download_button,
            "⬇ Results (JSON)",
            data=st.session_state[_K_JSON],
            file_name="adjustment_results.json",
            mime="application/json",
        )
    if st.session_state.get(_K_CSV):
        _stretch(
            a3.download_button,
            "⬇ Summary (CSV)",
            data=st.session_state[_K_CSV],
            file_name="adjustment_summary.csv",
            mime="text/csv",
        )

    st.markdown(
        "<div class='meta'>"
        f"<span>Period <b>{_e(period)}</b></span>"
        + (f"<span>Currency <b>{_e(fc)}</b></span>" if fc else "")
        + f"<span>Source <b>{_e(source)}</b></span>"
        f"<span>Generated <b>{_e(generated)}</b></span></div>",
        unsafe_allow_html=True,
    )

    if not results:
        st.info("This run produced no entries. Check that the adjustments file has an `entries` list.")
        return

    st.markdown(
        "<div class='section-title' style='margin-top:1rem;'>Validation summary</div>"
        "<div class='section-hint'>A concise view of the posting decisions produced by the validation engine.</div>",
        unsafe_allow_html=True,
    )
    _summary(results)
    st.markdown("<hr>", unsafe_allow_html=True)

    selected = _results_table(results, fc)
    if selected:
        st.markdown("<hr>", unsafe_allow_html=True)
        _entry_detail(selected, fc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _sidebar() -> None:
    with st.sidebar:
        st.markdown(
            "<div style='font-size:18px;font-weight:700;color:#172033;margin:3px 0 14px;'>FinAudit AI</div>",
            unsafe_allow_html=True,
        )
        st.caption("FINANCIAL CONTROLS")
        st.radio(
            "Navigation",
            ["Dashboard", "Validation", "Human Review", "Reports"],
            index=0,
            key="nav_section",
            label_visibility="collapsed",
        )
        st.markdown("---")
        st.caption("WORKFLOW")
        st.markdown(
            "① Upload data<br>② Validate entries<br>③ Review findings",
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.caption("CONTROL MODEL")
        st.markdown(
            "<span class='chip info'>Deterministic checks</span>"
            "<span class='chip info'>AI explanations</span>",
            unsafe_allow_html=True,
        )

def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    _sidebar()
    _header()

    # Step 2 is only shown while processing; never persist it. Results need data.
    step = st.session_state.get(_K_STEP, 1)
    if step != 3 or _K_RESULTS not in st.session_state:
        step = 1

    stepper = st.empty()
    stepper.markdown(
        "<div class='workflow'>" + _stepper_html(step) + "</div>",
        unsafe_allow_html=True,
    )

    if step == 3:
        _step_results()
        return

    action, payload = _step_upload()
    if action is None:
        return

    stepper.markdown(
        "<div class='workflow'>" + _stepper_html(2) + "</div>",
        unsafe_allow_html=True,
    )

    if action == "demo":
        coa_path = _DEMO_DATA_DIR / "chart_of_accounts.csv"
        adj_path = _DEMO_DATA_DIR / "manual_adjustments.json"
        if not coa_path.exists() or not adj_path.exists():
            stepper.markdown(
        "<div class='workflow'>" + _stepper_html(1) + "</div>",
        unsafe_allow_html=True,
    )
            st.error("Demo data not found. Expected `chart_of_accounts.csv` and "
                     "`manual_adjustments.json` in the `data/` folder.")
            return
        ok = _run_with_steps(coa_path, adj_path, source_label="demo")
    else:
        ok = _run_with_steps(payload["coa_bytes"], payload["adj_data"], source_label="upload")

    if ok:
        st.rerun()
    else:
        stepper.markdown(
        "<div class='workflow'>" + _stepper_html(1) + "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()