from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.agents import run_ds1_backend
from src.decision_agent import build_decision_card
from src.runtime_log import build_sample_runtime_log, write_json
from src.team_pack import DEFAULT_WORKBOOK, load_team_pack

ROOT = Path(__file__).parent
WORKBOOK = ROOT / DEFAULT_WORKBOOK
POLICY = ROOT / "config" / "policies.yaml"

st.set_page_config(page_title="OPC AI Agent Dashboard", layout="wide", page_icon="OPC")
st.markdown("""
<style>
.block-container { padding-top: 1.25rem; padding-bottom: 2rem; }
.badge { display:inline-block; border:1px solid #d8dee8; border-radius:6px; padding:4px 8px; margin-right:6px; font-size:12px; font-weight:700; background:#fff; }
.good { color:#067647; border-color:#abefc6; background:#ecfdf3; }
.warn { color:#b54708; border-color:#fedf89; background:#fffaeb; }
.blue { color:#175cd3; border-color:#b2ddff; background:#eff8ff; }
.state-box { border-left:5px solid #b42318; padding:10px 12px; background:#fff5f6; border-radius:6px; margin-bottom:10px; }
.state-ok { border-left-color:#067647; background:#f3fff7; }
</style>
""", unsafe_allow_html=True)


def money(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B VND"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.0f}M VND"
    return f"{value:,.0f} VND"


@st.cache_data(show_spinner="Loading live Team Pack Excel...")
def load_demo_data() -> tuple[dict, object, str, str]:
    team_pack = load_team_pack(WORKBOOK)
    backend = run_ds1_backend(WORKBOOK, POLICY)
    workbook_hash = hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()[:10]
    loaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return team_pack, backend, workbook_hash, loaded_at


team_pack, backend, workbook_hash, loaded_at = load_demo_data()

if "ap1_status" not in st.session_state:
    st.session_state.ap1_status = "pending"
if "final_state" not in st.session_state:
    st.session_state.final_state = "BLOCKED_BY_AP1" if backend.risk.financial_flow_paused else "DECISION_READY"
if "human_approval_id" not in st.session_state:
    st.session_state.human_approval_id = None

use_openai = st.sidebar.toggle("Use OpenAI live", value=True, help="Falls back safely if OPENAI_API_KEY is missing or API fails.")
page = st.sidebar.radio("Screen", ["Overview", "CON-004 Detail", "System Evidence"], index=0)

st.title("OPC AI Agent Dashboard")
st.markdown(
    '<span class="badge good">DATA: LIVE EXCEL</span>'
    f'<span class="badge {"good" if use_openai else "warn"}">OPENAI: {"LIVE/FALLBACK" if use_openai else "FALLBACK"}</span>'
    '<span class="badge blue">BANK API: MOCK / SANDBOX</span>',
    unsafe_allow_html=True,
)
st.caption(f"Workbook: {WORKBOOK.name} | Input hash: {workbook_hash} | Analysis timestamp: {loaded_at}")

finance = backend.finance.d5_handoff
risk = backend.risk.d5_handoff
decision_card = build_decision_card(
    backend,
    team_pack,
    use_openai=use_openai,
    ap1_status=st.session_state.ap1_status,
    final_state=st.session_state.final_state,
    human_approval_id=st.session_state.human_approval_id,
)

if page == "Overview":
    st.subheader("Input Data & Business Snapshot")
    audit = backend.finance.source_audit
    total_records = sum(audit.row_counts.values()) if audit else 0
    cols = st.columns(4)
    cols[0].metric("DS1 sheets loaded", f"{len(audit.loaded_sheets)}/8 core")
    cols[1].metric("Records validated", f"{total_records}")
    cols[2].metric("Schema errors", "0" if audit.core_complete else len(audit.missing_sheets))
    cols[3].metric("Source audit", "PASS" if audit.core_complete else "BLOCKED")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cash reserve breach", f"{backend.finance.cashflow.breach_count}/{len(backend.finance.cashflow.months)} months")
    c2.metric("Decision package ask", money(finance.decision_package_total_ask_vnd), finance.worst_month)
    c3.metric("Critical TXN cluster", money(risk.transaction_hold_amount_vnd), "TXN-006 / TXN-007")
    active_candidates = [x for x in backend.finance.credit_candidates if x.candidate_status != "hold"]
    held_candidates = [x for x in backend.finance.credit_candidates if x.candidate_status == "hold"]
    c4.metric("Credit cases", f"{len(active_candidates)} active / {len(held_candidates)} hold")

    left, right = st.columns([0.55, 0.45])
    with left:
        st.markdown("#### Live Source Rows")
        st.dataframe(pd.DataFrame([{"sheet": k, "rows": v} for k, v in audit.row_counts.items()]), use_container_width=True, hide_index=True)
    with right:
        st.markdown("#### Contract Priority")
        contracts = pd.DataFrame(team_pack.get("04_CONTRACTS", []))
        if not contracts.empty:
            wanted = [col for col in ["contract_id", "status", "contract_value", "gross_margin"] if col in contracts.columns]
            show = contracts[wanted].copy()
            show["priority"] = show["contract_id"].apply(lambda x: "1 - CRITICAL" if x == "CON-004" else "watch")
            st.dataframe(show.sort_values("priority"), use_container_width=True, hide_index=True)
        st.info("Demo action: choose CON-004 Detail in the sidebar to drill down into the live approval flow.")

elif page == "CON-004 Detail":
    st.subheader("CON-004 Detail - 3 Zone Decision Workspace")
    z1, z2, z3 = st.columns([0.25, 0.35, 0.40], gap="medium")

    with z1:
        st.markdown("### Zone 1")
        st.caption("Raw evidence panels")
        st.markdown("**Data Health**")
        st.write(f"8/8 DS1 core sheets loaded: `{backend.finance.source_audit.core_complete}`")
        st.write(f"Input hash: `{workbook_hash}`")
        st.write(f"Timestamp: `{loaded_at}`")
        st.markdown("**Masked Evidence**")
        st.json({note.field_name: note.tokenized_value or note.masked_value for note in backend.risk.safe_handling_notes})
        with st.expander("Cashflow rows"):
            st.dataframe(pd.DataFrame([m.model_dump() for m in backend.finance.cashflow.months]), use_container_width=True)
        with st.expander("Bank transactions flagged"):
            st.dataframe(pd.DataFrame([x.model_dump() for x in backend.risk.transaction_findings]), use_container_width=True)

    with z2:
        st.markdown("### Zone 2")
        st.caption("Agent workflow")
        blocked = st.session_state.ap1_status != "approved" and risk.financial_flow_paused
        st.markdown(
            f'<div class="state-box {"" if blocked else "state-ok"}"><b>Join status:</b> '
            f'{"BLOCKED BY CRITICAL RISK" if blocked else "AP1 RESOLVED - DECISION READY"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("**Finance & Data Agent**")
        st.write(f"Worst month: `{finance.worst_month}` | Funding package ask: **{money(finance.decision_package_total_ask_vnd)}**")
        st.write(f"Open invoices: **{money(finance.open_invoices_total_vnd)}** | Margin warnings: `{', '.join(finance.margin_warning_contract_ids)}`")
        st.markdown("**Risk & Compliance Agent**")
        txn_ids = risk.transaction_hold.txn_ids if risk.transaction_hold else []
        st.write(f"RR-001 cluster: `{', '.join(txn_ids)}` | Exposure: **{money(risk.transaction_hold_amount_vnd)}**")
        st.write(f"Financial flow paused: `{risk.financial_flow_paused}` | Execution risks: `{', '.join(risk.execution_risk_order_ids)}`")
        st.markdown("**Decision & Partner Agent**")
        st.dataframe(pd.DataFrame(decision_card["bank_fit_matrix"]), use_container_width=True, hide_index=True)
        st.warning("CR-003 is held because supplier confirmation is missing. The agent asks for more information and does not invent evidence.")

    with z3:
        st.markdown("### Zone 3")
        st.caption("Decision support")
        tab1, tab2, tab3 = st.tabs(["Recommendation", "Cashflow", "Credit Package"])
        with tab1:
            if blocked:
                st.error("Decision Card is gated. Approve AP-1 first to continue.")
            st.metric("Recommendation", decision_card["recommendation"])
            st.write(decision_card["rationale"])
            st.markdown("**Conditions**")
            for condition in decision_card["conditions"]:
                st.write(f"- {condition}")
            st.markdown("**Conflicts detected**")
            st.json(decision_card["conflicts_detected"])
        with tab2:
            cash = pd.DataFrame([m.model_dump() for m in backend.finance.cashflow.months])
            st.line_chart(cash.set_index("month")[["funding_need_vnd", "reserve_gap_vnd"]])
        with tab3:
            st.metric("Financial ask", money(decision_card["financial_ask"]["total"]))
            st.metric("Collateral total", money(decision_card["financial_ask"]["collateral_total"]))
            st.dataframe(pd.DataFrame(decision_card["financial_ask"]["breakdown"]), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("#### Approval Queue")
        st.dataframe(pd.DataFrame(decision_card["approval_required"]), use_container_width=True, hide_index=True)
        a, b = st.columns(2)
        if a.button("Approve AP-1 hold", type="primary", use_container_width=True):
            st.session_state.ap1_status = "approved"
            st.session_state.final_state = "DECISION_READY"
            st.session_state.human_approval_id = "APR-001"
            st.rerun()
        if b.button("Request more info", use_container_width=True):
            st.session_state.final_state = "NEED_MORE_INFORMATION"
            st.session_state.human_approval_id = "APR-NEEDINFO-001"
            st.rerun()
        c, d, e = st.columns(3)
        if c.button("Approve package", use_container_width=True):
            st.session_state.final_state = "ACTIVE"
            st.session_state.human_approval_id = "APR-FINAL-APPROVE"
            st.rerun()
        if d.button("Reject", use_container_width=True):
            st.session_state.final_state = "REJECTED"
            st.session_state.human_approval_id = "APR-FINAL-REJECT"
            st.rerun()
        if e.button("Renegotiate", use_container_width=True):
            st.session_state.final_state = "RENEGOTIATE"
            st.session_state.human_approval_id = "APR-FINAL-RENEGOTIATE"
            st.rerun()

        if st.button("Export sample runtime log", use_container_width=True):
            log_path = write_json(ROOT / "runtime_logs" / "sample_runtime_log.json", build_sample_runtime_log(decision_card))
            card_path = write_json(ROOT / "output" / "demo_decision_card.json", decision_card)
            st.success(f"Exported {log_path.name} and {card_path.name}")

else:
    st.subheader("System Evidence")
    st.markdown("#### Backend Output")
    st.json(backend.model_dump(mode="json"))
    st.markdown("#### Decision Card")
    st.json(decision_card)
    st.markdown("#### Runtime Log Preview")
    st.json(build_sample_runtime_log(decision_card))
