from __future__ import annotations

import base64
import hashlib
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.agents import run_ds1_backend
from src.decision_agent import (
    CREDIT_TO_API,
    build_bank_fit_matrix,
    build_decision_card,
    call_bank_api_mock,
)
from src.runtime_log import build_sample_runtime_log, write_json
from src.security import _stable_token
from src.team_pack import (
    DEFAULT_WORKBOOK,
    load_team_pack,
)
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
ASSETS = ROOT / "assets"
LOCAL_WORKBOOK = ROOT / DEFAULT_WORKBOOK
EXTERNAL_V3_WORKBOOK = ROOT.parent / "MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx"
WORKBOOK = EXTERNAL_V3_WORKBOOK if EXTERNAL_V3_WORKBOOK.exists() else LOCAL_WORKBOOK
POLICY = ROOT / "config" / "policies.yaml"
OPENAI_NARRATIVE_CACHE_VERSION = "decision-narrative-v1"
OPENAI_NARRATIVE_FIELDS = (
    "conflicts_detected",
    "conditions",
    "rationale",
    "llm_meta",
)

st.set_page_config(
    page_title="MIS-OPC Governance Console",
    layout="wide",
    page_icon=str(ASSETS / "mo-logo.svg"),
    initial_sidebar_state="expanded",
)
st.markdown(
    """
<style>
:root {
    --ink:#12172b; --ink-2:#1f263d; --canvas:#eef1ec; --panel:#ffffff;
    --line:#d8ddd4; --muted:#667085; --green:#1f6b51; --green-soft:#e3f1eb;
    --purple:#6a3fa0; --purple-soft:#f2eafa; --amber:#875500; --amber-soft:#fff4df;
    --red:#bd3d35; --red-soft:#fff0ed; --blue-soft:#edf3fb;
}
html, body, [class*="css"] { font-family:"IBM Plex Sans","Segoe UI",Arial,sans-serif; }
*, *::before, *::after { box-sizing:border-box; }
code, pre, .mono { font-family:"IBM Plex Mono","Cascadia Mono",Consolas,monospace; }
.stApp { background:var(--canvas); color:var(--ink); }
.block-container { padding:.65rem 1.75rem 2.5rem; max-width:1500px; }
[data-testid="stMainBlockContainer"] { max-width:none!important; padding-left:28px!important; padding-right:28px!important; }
header[data-testid="stHeader"] { height:2.75rem; background:transparent; pointer-events:none; }
[data-testid="stToolbar"] { display:flex!important; background:transparent!important; pointer-events:none!important; }
[data-testid="stToolbar"] > * { visibility:hidden!important; }
[data-testid="stExpandSidebarButton"], [data-testid="stExpandSidebarButton"] * {
    visibility:visible!important; pointer-events:auto!important;
}
div[data-testid="stDecoration"] { display:none; }
[data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {
    display:flex!important; position:fixed!important; top:8px!important; left:8px!important;
    z-index:10000!important; pointer-events:auto!important;
}
[data-testid="stSidebarCollapsedControl"] button, [data-testid="stExpandSidebarButton"] {
    background:#fff!important; color:var(--ink)!important; border:1px solid var(--line)!important;
    border-radius:7px!important; box-shadow:0 4px 14px rgba(18,23,43,.14)!important;
}
[data-testid="stSidebarCollapseButton"] {
    display:flex!important; position:absolute!important; top:8px!important; right:8px!important;
    z-index:10000!important; color:var(--ink)!important; background:#fff!important;
    border:1px solid var(--line)!important; border-radius:7px!important; pointer-events:auto!important;
}
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarCollapseButton"] svg {
    display:flex!important; color:var(--ink)!important; fill:var(--ink)!important;
    stroke:var(--ink)!important; opacity:1!important;
}
section[data-testid="stSidebar"] { background:#f7f8f4; border-right:1px solid var(--line); color:var(--ink); }
section[data-testid="stSidebar"] > div { padding-top:1rem; }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:var(--ink)!important; }
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color:var(--muted)!important; }
h1,h2,h3,h4 { color:var(--ink); letter-spacing:-.01em; }
.console-header { position:sticky; top:0; z-index:999; margin:0 0 16px; padding:14px 18px; min-height:68px; background:var(--ink); color:#fff; border-bottom:3px solid var(--purple); box-shadow:0 10px 28px rgba(18,23,43,.16); display:flex; align-items:center; justify-content:space-between; gap:16px; border-radius:0 0 10px 10px; }
.console-brand { display:flex; align-items:center; gap:12px; min-width:300px; }
.brand-logo { width:34px; height:34px; flex:0 0 34px; }
.console-title { color:#fff; font-size:16px; font-weight:800; line-height:1.1; }
.console-trace { margin-top:5px; color:#9aa4ba; font-size:10.5px; letter-spacing:.02em; font-family:"IBM Plex Mono",Consolas,monospace; }
.header-badges { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.badge { display:inline-flex; align-items:center; gap:7px; border:1px solid rgba(255,255,255,.2); border-radius:999px; padding:6px 10px; font-size:10px; font-weight:700; background:rgba(255,255,255,.055); color:#f8fafc; font-family:"IBM Plex Mono",Consolas,monospace; white-space:nowrap; }
.dot { width:7px; height:7px; border-radius:50%; display:inline-block; box-shadow:0 0 0 3px rgba(255,255,255,.06); }
.dot-green { background:#35d07f; animation:pulse 1.55s ease-in-out infinite; }
.dot-yellow { background:#f2b94b; } .dot-blue { background:#69a7ff; } .dot-red { background:#f56a62; }
@keyframes pulse { 0%,100%{opacity:.55;transform:scale(.92)} 50%{opacity:1;transform:scale(1.08)} }
.scope-strip { display:flex; flex-wrap:wrap; gap:6px; margin:-5px 0 10px; color:#5c6678; font-size:10px; }
.scope-pill { background:rgba(255,255,255,.72); border:1px solid var(--line); border-radius:999px; padding:4px 8px; }
.section-title { font-size:22px; line-height:1.25; font-weight:850; color:var(--ink); margin:.15rem 0 1rem; }
.zone-label { display:flex; align-items:center; gap:9px; margin:0 0 11px; font-size:13px; font-weight:850; color:var(--ink); }
.zone-chip { display:inline-flex; align-items:center; background:var(--ink); color:#fff; padding:4px 9px; border-radius:5px; font-size:9px; letter-spacing:.08em; font-family:"IBM Plex Mono",Consolas,monospace; }
div[data-testid="stVerticalBlockBorderWrapper"] { background:rgba(255,255,255,.93); border-color:var(--line)!important; border-radius:10px!important; box-shadow:0 1px 3px rgba(18,23,43,.035); }
.snapshot-panel { background:rgba(255,255,255,.94); border:1px solid var(--line); border-radius:10px; padding:11px 15px 12px; margin-bottom:12px; box-shadow:0 1px 3px rgba(18,23,43,.035); }
.snapshot-panel .zone-label { margin-bottom:8px; }
.snapshot-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:7px; }
.snapshot-card { border:1px solid var(--line); border-radius:8px; padding:7px 10px; min-height:59px; background:#fff; }
.snapshot-card.health { background:var(--green-soft); border-color:#c6dfd3; }
.snapshot-kicker { color:#6b7280; font-size:9.5px; line-height:1.2; margin-bottom:4px; }
.snapshot-value { color:var(--ink); font-size:18px; line-height:1.05; font-weight:850; overflow-wrap:anywhere; }
.snapshot-card.health .snapshot-value { color:var(--green); }
.snapshot-sub { margin-top:4px; color:#6b7280; font-size:8.5px; font-family:"IBM Plex Mono",Consolas,monospace; }
.snapshot-card.warn .snapshot-value { color:var(--amber); } .snapshot-card.danger .snapshot-value { color:var(--red); }
.metric-card { border:1px solid var(--line); border-radius:8px; padding:9px 11px; min-height:72px; box-shadow:none; overflow:hidden; background:#fff; }
.metric-blue { background:var(--blue-soft); } .metric-green { background:var(--green-soft); }
.metric-amber { background:var(--amber-soft); } .metric-rose { background:var(--red-soft); } .metric-gray { background:#f8fafc; }
.metric-label { color:#596273; font-size:11.5px; font-weight:700; margin-bottom:7px; }
.metric-value { color:var(--ink); font-size:18px; line-height:1.12; font-weight:850; overflow-wrap:anywhere; }
.metric-delta { display:inline-block; color:var(--green); background:#d8ece2; padding:3px 7px; border-radius:999px; font-size:10.5px; font-weight:750; margin-top:8px; }
.metric-delta-warn { color:var(--amber); background:#ffebc6; }
.stepper { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:6px; margin:8px 0 15px; }
.step { text-align:center; border-radius:6px; padding:8px 5px; background:#edeee9; color:#a0a49d; font-size:9px; font-weight:700; font-family:"IBM Plex Mono",Consolas,monospace; }
.step-done { background:#e2f1e9; color:var(--green); } .step-active { background:var(--ink); color:#fff; box-shadow:0 4px 12px rgba(18,23,43,.16); }
.contract-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin:6px 0 12px; }
.contract-title { color:var(--ink); font-size:19px; line-height:1.2; font-weight:850; }
.contract-sub { color:#687184; font-size:11.5px; margin-top:4px; }
.state-pill { flex:0 0 auto; border-radius:999px; padding:6px 11px; background:#eaf0f9; color:#365780; font-size:10px; font-family:"IBM Plex Mono",Consolas,monospace; }
.state-box { border:1px solid #f1b7b1; padding:13px 14px; background:var(--red-soft); border-radius:8px; margin-bottom:12px; color:#8f2f29; }
.state-ok { border-color:#bddccb; background:var(--green-soft); color:var(--green); }
.info-card { border:1px solid #d7dbe3; border-left:4px solid var(--purple); background:#fbf9ff; border-radius:8px; padding:12px 14px; margin:9px 0; color:#2c3447; font-size:12.5px; }
.info-card strong { color:var(--ink); }
.next-step { border:1px solid #c7d9ce; background:#edf7f1; border-radius:8px; padding:13px 14px; margin:10px 0 13px; color:#245b45; font-size:12.5px; }
.next-step-label { font-family:"IBM Plex Mono",Consolas,monospace; font-size:9px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; margin-bottom:5px; }
.source-tag { display:inline-block; border-radius:5px; padding:3px 7px; font-size:9px; font-weight:800; margin-right:6px; font-family:"IBM Plex Mono",Consolas,monospace; }
.tag-det { background:#e7f0fb; color:#31577c; } .tag-gpt { background:#efe5fa; color:#7240a5; }
.decision-card { border:1px solid var(--ink); border-radius:9px; overflow:hidden; margin:10px 0 14px; background:#fff; }
.decision-head { background:var(--ink); color:#fff; padding:12px 14px; display:flex; justify-content:space-between; align-items:center; gap:12px; }
.decision-kicker { color:#a8b1c7; font:10px "IBM Plex Mono",Consolas,monospace; margin-bottom:4px; }
.decision-state { font:10.5px "IBM Plex Mono",Consolas,monospace; color:#fff; }
.decision-rec { background:#222941; color:#d99a2b; padding:6px 9px; border-radius:6px; font:700 10px "IBM Plex Mono",Consolas,monospace; }
.decision-body { display:grid; grid-template-columns:1fr 1fr; gap:14px; padding:14px; }
.decision-section { margin-bottom:12px; }
.decision-section:last-child { margin-bottom:0; }
.decision-section-title { color:var(--ink); font-size:12px; font-weight:850; margin:0 0 7px; }
.decision-row { display:flex; justify-content:space-between; gap:10px; padding:7px 0; border-bottom:1px solid #e3e6e1; color:#2f3748; font-size:11.5px; }
.decision-row:last-child { border-bottom:0; }
.decision-total { font-size:17px; font-weight:850; color:var(--ink); }
.decision-note { padding:9px 10px; border-radius:7px; background:#faf8fc; color:#3b4253; font-size:11.5px; margin-bottom:7px; }
.decision-note.gpt { background:var(--purple-soft); border:1px solid #dbc7ef; }
.upside { grid-column:1/-1; background:var(--green-soft); border:1px solid #c2decf; color:#245e47; border-radius:8px; padding:11px 12px; font-size:11.5px; }
.runtime-log { background:var(--ink); border-radius:8px; padding:10px 12px; margin:7px 0 13px; }
.runtime-row { display:grid; grid-template-columns:54px 72px 1fr; gap:7px; padding:6px 0; border-bottom:1px solid rgba(255,255,255,.09); color:#c7cede; font:9.5px "IBM Plex Mono",Consolas,monospace; }
.runtime-row:last-child { border-bottom:0; } .runtime-time { color:#727e9d; } .runtime-agent { color:#43dc8c; font-weight:800; }
.evidence-card { border:1px solid var(--line); border-radius:8px; padding:11px 12px; background:#fff; font-size:11px; color:#344054; }
.evidence-line { display:flex; justify-content:space-between; gap:8px; padding:6px 0; border-bottom:1px solid #e2e5df; }
.evidence-line:last-child { border-bottom:0; } .evidence-good { color:var(--green); }
.confidence-track { height:5px; border-radius:999px; background:#e7e7e3; overflow:hidden; margin-top:5px; }
.confidence-fill { height:100%; background:var(--purple); }
.hold-card { border:1px dashed #ce841c; background:var(--amber-soft); border-radius:8px; padding:12px 14px; margin:10px 0; color:#75500f; }
.agent-brief { color:#2f3748; font-size:11.5px; line-height:1.45; }
.agent-brief-row { padding:5px 0; border-bottom:1px solid #e3e6e1; }
.agent-brief-row:last-child { border-bottom:0; }
.agent-brief .critical { color:var(--red); font-weight:800; }
.sidebar-block { border-top:1px solid #e1e5de; padding-top:13px; margin-top:13px; }
div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:8px; overflow:hidden; }
div[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:8px; padding:10px 12px; box-shadow:none; }
.stButton > button { min-height:38px; border-radius:7px; border:1px solid #c9cec7; background:#fff; color:var(--ink)!important; font-weight:750; cursor:pointer; }
.stButton > button:hover { border-color:var(--purple); color:#4f2b78!important; background:#fbf8ff; }
.stButton > button:focus-visible { outline:3px solid rgba(106,63,160,.3); outline-offset:2px; }
.stButton > button[kind="primary"] { background:var(--ink)!important; color:#fff!important; border-color:var(--ink)!important; }
.stButton > button[kind="primary"]:hover { background:#202842!important; color:#fff!important; }
.stButton > button:disabled { border-color:#dfe2dd!important; color:#596273!important; background:#f0f1ed!important; cursor:not-allowed; opacity:1; }
.stTabs [data-baseweb="tab-highlight"] { background-color:var(--purple); }
.stTabs [data-baseweb="tab"] { color:#4b5563; font-weight:750; }
.stTabs [aria-selected="true"] { color:var(--ink)!important; }
div[data-testid="stExpander"] { background:#fff; border-color:var(--line); border-radius:8px; }
.stMarkdown h5 { font-size:14px; margin:.15rem 0 .45rem; }
@media (max-width:1100px) { .snapshot-grid{grid-template-columns:repeat(2,minmax(0,1fr));} .console-header{position:relative;} .decision-body{grid-template-columns:1fr;} .upside{grid-column:auto;} }
@media (max-width:760px) { .block-container{padding-left:.75rem;padding-right:.75rem;} .console-header{align-items:flex-start;flex-direction:column;} .header-badges{justify-content:flex-start;} .snapshot-grid{grid-template-columns:1fr;} .stepper{grid-template-columns:1fr;} .contract-heading{flex-direction:column;} }
</style>
""",
    unsafe_allow_html=True,
)


def money(value: int | float | None) -> str:
    if value is None:
        return "không áp dụng"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} tỷ VND"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.0f} triệu VND"
    return f"{value:,.0f} VND"


def asset_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


MO_LOGO_URI = asset_data_uri(ASSETS / "mo-logo.svg")
WARNING_URI = asset_data_uri(ASSETS / "warning.svg")


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def object_dump(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return obj
    return dict(getattr(obj, "__dict__", {}))


def openai_narrative_signature(
    backend: Any,
    team_pack: dict[str, Any],
    model: str,
) -> str:
    """Fingerprint only the deterministic inputs sent to the narrative model."""

    prompt_payload = {
        "cache_version": OPENAI_NARRATIVE_CACHE_VERSION,
        "model": model,
        "finance_handoff": object_dump(backend.finance.d5_handoff),
        "risk_handoff": object_dump(backend.risk.d5_handoff),
        "bank_fit_matrix": build_bank_fit_matrix(
            backend,
            team_pack.get("11_BANK_PRODUCTS", []),
        ),
    }
    encoded = json.dumps(
        prompt_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def df_from_sheet(team_pack: dict[str, Any], sheet: str) -> pd.DataFrame:
    data = team_pack.get(sheet, [])
    return pd.DataFrame(data)


def _tokenize_df(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    safe = frame.copy()
    for column in columns:
        if column in safe.columns:
            safe[column] = safe[column].apply(
                lambda value: (
                    _stable_token(column, str(value))
                    if pd.notna(value) and not str(value).startswith("TOK-")
                    else value
                )
            )
    return safe


def _tokenize_record(record: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    if not record:
        return {}
    return _tokenize_df(pd.DataFrame([record]), columns).iloc[0].to_dict()


def metric_card(label: str, value: str, delta: str | None = None, tone: str = "gray", warn: bool = False) -> None:
    delta_html = ""
    if delta:
        klass = "metric-delta metric-delta-warn" if warn else "metric-delta"
        delta_html = f'<div class="{klass}">{delta}</div>'
    st.markdown(
        f'''
        <div class="metric-card metric-{tone}">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            {delta_html}
        </div>
        ''',
        unsafe_allow_html=True,
    )


def render_snapshot_panel(cards: list[dict[str, str]], title: str = "Data Health & Business Snapshot") -> None:
    items = []
    for card in cards:
        classes = "snapshot-card " + esc(card.get("class", ""))
        items.append(
            f'''<div class="{classes}">
                <div class="snapshot-kicker">{esc(card.get("label", ""))}</div>
                <div class="snapshot-value">{esc(card.get("value", ""))}</div>
                <div class="snapshot-sub">{esc(card.get("sub", ""))}</div>
            </div>'''
        )
    st.markdown(
        f'''<section class="snapshot-panel">
            <div class="zone-label"><span class="zone-chip">ZONE 1</span>{esc(title)}</div>
            <div class="snapshot-grid">{"".join(items)}</div>
        </section>''',
        unsafe_allow_html=True,
    )



def render_console_header(openai_label: str, openai_class: str) -> None:
    openai_dot = "dot-green" if openai_class == "good" else "dot-yellow"
    st.markdown(
        f"""
        <div class="console-header">
            <div class="console-brand">
                <img class="brand-logo" src="{MO_LOGO_URI}" alt="MO logo" />
                <div>
                    <div class="console-title">MIS-OPC · Governance Console</div>
                    <div class="console-trace">TRACE-2026-CON004 · DEC-v1 · {datetime.now().strftime("%H:%M:%S")}</div>
                </div>
            </div>
            <div class="header-badges">
                <span class="badge"><span class="dot dot-green"></span>DATA: LIVE EXCEL</span>
                <span class="badge"><span class="dot {openai_dot}"></span>OPENAI: {openai_label}</span>
                <span class="badge"><span class="dot dot-yellow"></span>BANK API: MOCK</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_scope_strip() -> None:
    st.markdown(
        f'''<div class="scope-strip">
            <span class="scope-pill">Tệp: {esc(WORKBOOK.name)}</span>
            <span class="scope-pill">Hash: {esc(workbook_hash)}</span>
            <span class="scope-pill">Kỳ: {esc(selected_period)}</span>
            <span class="scope-pill">Hợp đồng: {esc(selected_contract)}</span>
            <span class="scope-pill">Agent: {esc(agent_focus)}</span>
        </div>''',
        unsafe_allow_html=True,
    )


def zone_heading(zone: str, title: str) -> None:
    st.markdown(f'<div class="zone-label"><span class="zone-chip">{zone}</span>{title}</div>', unsafe_allow_html=True)


def info_card(title: str, body: str) -> None:
    st.markdown(f'<div class="info-card"><strong>{title}</strong><br>{body}</div>', unsafe_allow_html=True)


def current_stage(final_state: str) -> str:
    if final_state in {"ACTIVE", "REJECTED", "NEED_MORE_INFORMATION", "RENEGOTIATE"}:
        return "FINAL"
    if st.session_state.ap1_status != "approved":
        return "BLOCKED_AP1"
    if (
        st.session_state.ap2_status == "approved"
        and st.session_state.ap3_status == "approved"
        and st.session_state.ap4_status == "approved"
    ):
        return "DECISION_READY"
    return "PROPOSED"


def render_stepper(final_state: str) -> None:
    active = "ANALYZED" if detail_contract_id != "CON-004" else current_stage(final_state)
    labels = ["ANALYZED", "BLOCKED_AP1", "PROPOSED", "DECISION_READY", "FINAL"]
    active_index = labels.index(active)
    items = []
    for index, label in enumerate(labels):
        klass = "step-active" if index == active_index else "step-done" if index < active_index else ""
        items.append(f'<div class="step {klass}">{label}</div>')
    st.markdown('<div class="stepper">' + ''.join(items) + '</div>', unsafe_allow_html=True)


def render_contract_heading(contract_id: str, contract_row: dict[str, Any], state: str) -> None:
    name = (
        decision_card.get("contract_name", "Cooperative Network Rollout")
        if contract_id == "CON-004"
        else contract_row.get("contract_name")
        or contract_row.get("description")
        or "Contract precheck"
    )
    st.markdown(
        f'''<div class="contract-heading">
            <div>
                <div class="contract-title">{esc(contract_id)} · {esc(name)}</div>
                <div class="contract-sub">Khách hàng {esc(selected_customer_name(contract_row))} · Phạm vi {esc(selected_period)}</div>
            </div>
            <span class="state-pill">{esc(state)}</span>
        </div>''',
        unsafe_allow_html=True,
    )


def render_runtime_evidence(card: dict[str, Any]) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    events = [
        (now, "INGESTION", "14 sheets validated"),
        (now, "FINANCE", "Cashflow and margin analyzed"),
        (now, "RISK", "RR-001 critical cluster detected"),
        (now, "GOVERNANCE", "AP-1 created"),
    ]
    if st.session_state.ap1_status == "approved":
        events.extend(
            [
                (now, "FOUNDER", "AP-1 approved"),
                (now, "MASKING", "restricted fields tokenized"),
            ]
        )
    if st.session_state.ap4_status == "approved":
        events.append((now, "BANK_API", "AP-4 released sandbox precheck"))
    if st.session_state.ap1_status == "approved":
        llm_meta = card.get("llm_meta", {})
        mode = str(llm_meta.get("mode", "fallback")).upper()
        cache_status = str(llm_meta.get("cache_status", "BYPASS")).upper()
        if cache_status == "HIT":
            message = f"{mode} narrative reused · SESSION CACHE"
        elif cache_status == "MISS":
            message = f"{mode} synthesis completed · API CALL"
        else:
            message = f"{mode} deterministic narrative · NO API CALL"
        events.append((now, "OPENAI", message))
    rows = "".join(
        f'<div class="runtime-row"><span class="runtime-time">{esc(ts)}</span><span class="runtime-agent">{esc(agent)}</span><span>{esc(message)}</span></div>'
        for ts, agent, message in events
    )
    st.markdown(
        '<div class="mono" style="font-size:10px;color:#596273;margin-bottom:4px">Runtime Log</div>'
        + f'<div class="runtime-log">{rows}</div>',
        unsafe_allow_html=True,
    )


def render_openai_evidence(card: dict[str, Any]) -> None:
    meta = card.get("llm_meta", {})
    if st.session_state.ap1_status != "approved":
        st.markdown(
            '<div class="evidence-card" style="text-align:center;padding:26px 12px;color:#737b8d">OpenAI chưa được hiển thị trước khi AP-1 được xử lý.</div>',
            unsafe_allow_html=True,
        )
        return
    mode = str(meta.get("mode", "fallback")).upper()
    schema = str(meta.get("schema_validation", "NOT_RUN"))
    confidence = float(meta.get("confidence") or 0)
    latency = meta.get("latency_ms")
    latency_text = f"{float(latency) / 1000:.1f}s" if latency is not None else "n/a"
    cache_status = str(meta.get("cache_status", "BYPASS")).upper()
    narrative_source = {
        "MISS": "API CALL",
        "HIT": "SESSION CACHE",
        "BYPASS": "DETERMINISTIC",
    }.get(cache_status, cache_status)
    st.markdown(
        f'''<div class="evidence-card">
            <div class="evidence-line"><span>Status</span><span class="evidence-good">{esc(mode)}</span></div>
            <div class="evidence-line"><span>Model</span><span>{esc(meta.get("model", "gpt-4o"))}</span></div>
            <div class="evidence-line"><span>Narrative source</span><span>{esc(narrative_source)}</span></div>
            <div class="evidence-line"><span>Latency</span><span>{esc(latency_text)}</span></div>
            <div class="evidence-line"><span>Schema validation</span><span class="evidence-good">{esc(schema)}</span></div>
            <div style="padding-top:7px"><div class="evidence-line" style="border:0;padding:0"><span>Confidence</span><span>{confidence:.2f}</span></div>
            <div class="confidence-track"><div class="confidence-fill" style="width:{max(0, min(100, confidence * 100)):.0f}%"></div></div></div>
        </div>''',
        unsafe_allow_html=True,
    )


def render_decision_card(card: dict[str, Any]) -> None:
    financial_rows = "".join(
        f'''<div class="decision-row"><span>{esc(item.get("credit_id"))} → {esc(item.get("bank_product") or "đang ghép")}</span><strong>{esc(money(item.get("amount")))}</strong></div>'''
        for item in card.get("financial_ask", {}).get("breakdown", [])
    )
    risk_rows = "".join(
        f'''<div class="decision-note">{esc(item.get("description"))} · {esc(item.get("rule_ref"))} · {esc(item.get("severity"))}</div>'''
        for item in card.get("risks_remaining", [])
    ) or '<div class="decision-note">Không còn rủi ro mở ở trạng thái hiện tại.</div>'
    missing_rows = "".join(
        f'''<div class="decision-note">{esc(item.get("description"))}</div>'''
        for item in card.get("missing_evidence", [])
    ) or '<div class="decision-note">Không thiếu bằng chứng bắt buộc.</div>'
    conflict_rows = "".join(
        f'''<div class="decision-note gpt">{esc(item.get("description"))}<br><span style="color:#6d5a7f">Cách xử lý: {esc(item.get("resolution_note"))}</span></div>'''
        for item in card.get("conflicts_detected", [])
    ) or '<div class="decision-note gpt">Không phát hiện mâu thuẫn giữa Finance và Risk.</div>'
    condition_rows = "".join(
        f'<div class="decision-row"><span>{esc(condition)}</span></div>'
        for condition in card.get("conditions", [])
    )
    upside = card.get("upside_if_conditions_met", {})
    st.markdown(
        f'''<section class="decision-card">
            <div class="decision-head">
                <div><div class="decision-kicker">Decision Card · {esc(card.get("decision_version"))}</div><div class="decision-state">state: {esc(card.get("state"))}</div></div>
                <div class="decision-rec">{esc(card.get("recommendation"))}</div>
            </div>
            <div class="decision-body">
                <div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-det">deterministic</span>Financial ask</div>{financial_rows}<div class="decision-row"><span>Total</span><span class="decision-total">{esc(money(card.get("financial_ask", {}).get("total")))}</span></div></div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-det">deterministic</span>Risks remaining</div>{risk_rows}</div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-det">deterministic</span>Missing evidence</div>{missing_rows}</div>
                </div>
                <div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-gpt">gpt-generated</span>Conflicts detected</div>{conflict_rows}</div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-gpt">gpt-generated</span>Conditions</div>{condition_rows}</div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-gpt">gpt-generated</span>Rationale</div><div class="decision-note gpt">{esc(card.get("rationale"))}</div></div>
                </div>
                <div class="upside"><span class="source-tag tag-det">deterministic</span><strong>Upside nếu đủ điều kiện</strong><br>Gross profit {esc(money(upside.get("gross_profit_vnd")))} · phục hồi tháng {esc(upside.get("recovery_month"))} · closing cash {esc(money(upside.get("recovery_closing_cash_vnd")))}<br>{esc(upside.get("narrative"))}</div>
            </div>
        </section>''',
        unsafe_allow_html=True,
    )


def founder_next_step() -> str:
    if detail_contract_id != "CON-004":
        return "Đọc Finance/Risk evidence của hợp đồng này; Decision Card sâu hiện chỉ áp dụng cho CON-004."
    if st.session_state.ap1_status != "approved":
        return "Bước tiếp theo: duyệt AP-1 để tạm giữ cụm TXN-006/007 trước khi xem Decision Card đầy đủ."
    if st.session_state.ap2_status != "approved" or st.session_state.ap3_status != "approved":
        return "Bước tiếp theo: duyệt AP-2 vốn lưu động và AP-3 bảo lãnh trước khi gửi hồ sơ ra ngoài."
    if st.session_state.ap4_status != "approved":
        return "Bước tiếp theo: duyệt AP-4 để mở Bank API sandbox và chuẩn bị submission đã masking."
    if st.session_state.final_state in {"ACTIVE", "REJECTED", "NEED_MORE_INFORMATION", "RENEGOTIATE"}:
        return "Quyết định cuối đã được ghi nhận; kiểm tra runtime log để chứng minh state thay đổi thật."
    return "Bước tiếp theo: chọn một quyết định cuối cùng: duyệt, từ chối, yêu cầu thêm thông tin hoặc đàm phán lại."

@st.cache_data(show_spinner="Đang đọc Team Pack Excel trực tiếp...")
def load_demo_data() -> tuple[dict, object, str, str]:
    team_pack = load_team_pack(WORKBOOK)
    backend = run_ds1_backend(WORKBOOK, POLICY)
    workbook_hash = hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()[:10]
    loaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return team_pack, backend, workbook_hash, loaded_at


team_pack, backend, workbook_hash, loaded_at = load_demo_data()
contracts_df = df_from_sheet(team_pack, "04_CONTRACTS")
orders_df = df_from_sheet(team_pack, "06_ORDERS")
invoices_df = df_from_sheet(team_pack, "07_INVOICES")
credit_df = df_from_sheet(team_pack, "10_CREDIT_PROFILE")
contract_ids = sorted(
    item.contract_id for item in backend.finance.margin_analysis
) or ["CON-004"]
contract_choices = ["Tất cả hợp đồng", *contract_ids]
default_contract = "CON-004" if "CON-004" in contract_ids else contract_ids[0]
default_contract_index = contract_choices.index(default_contract)

for key in ("ap1_status", "ap2_status", "ap3_status", "ap4_status"):
    if key not in st.session_state:
        st.session_state[key] = "pending"
if "final_state" not in st.session_state:
    st.session_state.final_state = "BLOCKED_BY_AP1" if backend.risk.financial_flow_paused else "DECISION_READY"
if "human_approval_id" not in st.session_state:
    st.session_state.human_approval_id = None
if "action_warning" not in st.session_state:
    st.session_state.action_warning = None
if "action_toast" not in st.session_state:
    st.session_state.action_toast = None
if "bank_api_response" not in st.session_state:
    st.session_state.bank_api_response = None
if "openai_narrative_cache" not in st.session_state:
    st.session_state.openai_narrative_cache = None
if st.session_state.action_toast:
    st.toast(st.session_state.action_toast)
    st.session_state.action_toast = None

st.sidebar.markdown("### Điều hướng")
page = st.sidebar.radio("Màn hình", ["Tổng quan", "Chi tiết hợp đồng", "Bằng chứng hệ thống"], index=0)

st.sidebar.markdown('<div class="sidebar-block"></div>', unsafe_allow_html=True)
st.sidebar.markdown("### Bộ lọc demo")
selected_period = st.sidebar.selectbox("Kỳ phân tích", ["6 tháng tới", "Quý hiện tại", "Tất cả dữ liệu"], index=0)
selected_contract = st.sidebar.selectbox("Hợp đồng trọng tâm", contract_choices, index=default_contract_index)
if selected_contract == "Tất cả hợp đồng":
    detail_contract_id = default_contract
    st.sidebar.caption(f"Tổng quan đang hiển thị toàn bộ. Trang chi tiết sẽ mở mặc định {detail_contract_id}.")
else:
    detail_contract_id = selected_contract
agent_focus = st.sidebar.selectbox("Agent đang xem", ["Tất cả agent", "Finance & Data", "Risk & Compliance", "Decision & Partner"], index=0)
openai_enabled = bool(os.getenv("OPENAI_API_KEY"))
openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
ap1_approved = st.session_state.ap1_status == "approved"
finance = backend.finance.d5_handoff
risk = backend.risk.d5_handoff
if finance is None or risk is None:
    st.error("Backend chưa tạo đủ handoff D5. Vui lòng chạy lại pipeline hoặc kiểm tra source audit.")
    st.stop()

narrative_signature = openai_narrative_signature(
    backend,
    team_pack,
    openai_model,
)

if ap1_approved and openai_enabled:
    if st.sidebar.button(
        "Tạo lại phân tích GPT",
        width="stretch",
        key="regenerate_openai_narrative",
        help="Bỏ narrative đang cache và thực hiện đúng một API call mới.",
    ):
        st.session_state.openai_narrative_cache = None

decision_args = {
    "ap1_status": st.session_state.ap1_status,
    "ap2_status": st.session_state.ap2_status,
    "ap3_status": st.session_state.ap3_status,
    "ap4_status": st.session_state.ap4_status,
    "final_state": st.session_state.final_state,
    "human_approval_id": st.session_state.human_approval_id,
}

# Approval/filter reruns always rebuild deterministic state without an API call.
decision_card = build_decision_card(
    backend,
    team_pack,
    use_openai=False,
    **decision_args,
)

narrative_cache = st.session_state.openai_narrative_cache
cache_is_current = (
    isinstance(narrative_cache, dict)
    and narrative_cache.get("signature") == narrative_signature
)
api_called_this_run = False

# GPT is called once after AP-1, or after relevant inputs/model change, or when
# the explicit regeneration button clears the cached narrative above.
if ap1_approved and openai_enabled and not cache_is_current:
    with st.spinner("GPT đang tổng hợp Decision Card..."):
        live_card = build_decision_card(
            backend,
            team_pack,
            use_openai=True,
            **decision_args,
        )
    narrative_cache = {
        "signature": narrative_signature,
        **{
            field: live_card.get(field)
            for field in OPENAI_NARRATIVE_FIELDS
        },
    }
    st.session_state.openai_narrative_cache = narrative_cache
    cache_is_current = True
    api_called_this_run = True

if ap1_approved and cache_is_current:
    for field in OPENAI_NARRATIVE_FIELDS:
        decision_card[field] = narrative_cache.get(field)
    decision_card["llm_meta"] = {
        **(decision_card.get("llm_meta") or {}),
        **(narrative_cache.get("llm_meta") or {}),
        "cache_status": "MISS" if api_called_this_run else "HIT",
        "cache_key": narrative_signature[:12],
    }
else:
    decision_card["llm_meta"] = {
        **(decision_card.get("llm_meta") or {}),
        "cache_status": "BYPASS",
    }

llm_mode = decision_card.get("llm_meta", {}).get("mode", "fallback")
if st.session_state.ap1_status != "approved":
    openai_label = "CHỜ AP-1"
    openai_class = "warn"
else:
    openai_label = {
        "live": "LIVE",
        "fallback": "DỰ PHÒNG",
        "fallback_after_invalid_schema": "SCHEMA FAILED",
        "fallback_after_error": "DỰ PHÒNG SAU LỖI",
    }.get(llm_mode, llm_mode.upper())
    openai_class = "good" if llm_mode == "live" else "warn"

render_console_header(openai_label, openai_class)
render_scope_strip()


def agent_visible(name: str) -> bool:
    return agent_focus == "Tất cả agent" or agent_focus == name


def filtered_cashflow_rows():
    months = list(backend.finance.cashflow.months)
    if selected_period == "Quý hiện tại":
        return months[:3]
    return months


def risk_visible(severity: str | None) -> bool:
    return True


def approval_rows_for_view() -> list[dict]:
    if detail_contract_id != "CON-004":
        return []
    return [dict(item) for item in decision_card["approval_required"]]


def selected_contract_row(contract_id: str) -> dict[str, Any]:
    if contracts_df.empty or "contract_id" not in contracts_df:
        return {}
    rows = contracts_df[contracts_df["contract_id"].astype(str) == contract_id]
    return rows.iloc[0].to_dict() if not rows.empty else {}


def selected_customer_name(contract_row: dict[str, Any]) -> str:
    customer_id = contract_row.get("customer_id")
    if not customer_id:
        return "không rõ"
    return _stable_token("customer_id", str(customer_id))


def related_orders(contract_id: str) -> pd.DataFrame:
    if orders_df.empty or "contract_id" not in orders_df:
        return pd.DataFrame()
    return orders_df[orders_df["contract_id"].astype(str) == contract_id].copy()


def related_invoices(order_rows: pd.DataFrame) -> pd.DataFrame:
    if invoices_df.empty or order_rows.empty or "order_id" not in order_rows or "order_id" not in invoices_df:
        return pd.DataFrame()
    order_ids = set(order_rows["order_id"].astype(str))
    return invoices_df[invoices_df["order_id"].astype(str).isin(order_ids)].copy()


def margin_for_contract(contract_id: str) -> dict[str, Any]:
    for item in getattr(backend.finance, "margin_analysis", []):
        data = object_dump(item)
        if str(data.get("contract_id")) == contract_id:
            return data
    row = selected_contract_row(contract_id)
    value = row.get("contract_value")
    margin = row.get("gross_margin")
    gross = value * margin if pd.notna(value) and pd.notna(margin) else None
    return {"contract_id": contract_id, "contract_value": value, "gross_margin": margin, "gross_profit_vnd": gross}


def execution_risks_for_contract(contract_id: str) -> list[dict[str, Any]]:
    risks = []
    order_ids = set(related_orders(contract_id).get("order_id", pd.Series(dtype=str)).astype(str))
    for item in getattr(backend.risk, "execution_risks", []):
        data = object_dump(item)
        if str(data.get("contract_id")) == contract_id or str(data.get("order_id")) in order_ids:
            data["severity"] = "High" if data.get("systemic") else "Medium"
            risks.append(data)
    return [item for item in risks if risk_visible(item.get("severity"))]


def related_credit_cases(contract_id: str) -> pd.DataFrame:
    if credit_df.empty:
        return pd.DataFrame()
    text_cols = [col for col in ["collateral_or_basis", "request_type", "precheck_note"] if col in credit_df.columns]
    mask = pd.Series(False, index=credit_df.index)
    for col in text_cols:
        mask = mask | credit_df[col].astype(str).str.contains(contract_id, case=False, na=False)
    if contract_id == "CON-004":
        mask = mask | credit_df["credit_case_id"].astype(str).isin(["CR-001", "CR-002", "CR-004"])
    if contract_id == "CON-005":
        mask = mask | credit_df["credit_case_id"].astype(str).isin(["CR-003"])
    if "credit_case_id" in credit_df.columns and not mask.any():
        mask = mask | credit_df["credit_case_id"].astype(str).eq("CR-001")
    return _tokenize_df(
        credit_df[mask].copy(),
        ["company_id", "customer_id"],
    )


def contract_status(contract_id: str) -> tuple[str, str]:
    margin = margin_for_contract(contract_id)
    risks = execution_risks_for_contract(contract_id)
    gross_margin = margin.get("gross_margin")
    if contract_id == "CON-004" and backend.risk.financial_flow_paused:
        return "CRITICAL", "Bị chặn bởi RR-001/AP-1"
    if risks:
        return "HIGH", "Có rủi ro triển khai cần theo dõi"
    if gross_margin is not None and pd.notna(gross_margin) and float(gross_margin) < 0.27:
        return "WATCH", "Biên lợi nhuận thấp hơn ngưỡng"
    return "OK", "Theo dõi bình thường"


def contract_summary_table() -> pd.DataFrame:
    intake_by_contract = {
        item.contract_id: item for item in backend.finance.intake
    }
    rows = []
    for assessment in backend.finance.margin_analysis:
        margin = object_dump(assessment)
        contract_id = str(margin["contract_id"])
        intake = intake_by_contract.get(contract_id)
        status, reason = contract_status(contract_id)
        rows.append(
            {
                "contract_id": contract_id,
                "customer_id": intake.customer_id if intake else None,
                "status": margin.get("status"),
                "contract_value_vnd": margin.get("contract_value_vnd"),
                "gross_margin": margin.get("gross_margin"),
                "gross_profit_vnd": margin.get("gross_profit_vnd"),
                "agent_priority": status,
                "reason": reason,
            }
        )
    table = _tokenize_df(pd.DataFrame(rows), ["customer_id"])
    if selected_contract != "Tất cả hợp đồng":
        table = table[table["contract_id"] == selected_contract]
    return table


def recommendation_for_contract(contract_id: str) -> tuple[str, str]:
    if contract_id == "CON-004":
        return decision_card.get("recommendation", "CONDITIONAL_RECOMMEND"), "Case có Decision Card đầy đủ, approval queue AP-1 đến AP-5 và bank fit matrix."
    status, reason = contract_status(contract_id)
    credits = related_credit_cases(contract_id)
    if status == "HIGH":
        return "NEEDS_REVIEW", f"{reason}. Cần kiểm tra execution risk trước khi mở gói tín dụng."
    if status == "WATCH":
        return "WATCH_MARGIN", f"{reason}. Có thể giữ trong pipeline nhưng cần điều kiện biên lợi nhuận/cashflow rõ hơn."
    if not credits.empty:
        return "PRECHECK_OK", f"Có {len(credits)} credit case liên quan; cần D&P Agent tổng hợp điều kiện cuối."
    return "MONITOR", "Chưa có credit case chuyên biệt trong workbook; tiếp tục theo dõi dữ liệu vận hành."


def snapshot_cards_for_view(contract_id: str) -> list[dict[str, str]]:
    audit = backend.finance.source_audit
    sheet_scope = {
        "Tất cả agent": (len(audit.loaded_sheets), "Finance 8 · Risk 12 · D&P 1"),
        "Finance & Data": (8, "Finance & Data sử dụng"),
        "Risk & Compliance": (12, "Risk & Compliance sử dụng"),
        "Decision & Partner": (1, "Decision & Partner sử dụng trực tiếp"),
    }
    sheet_count, sheet_sub = sheet_scope[agent_focus]
    total_records = sum(audit.row_counts.values())
    cards = [
        {"label": "Tổng số sheet đã đọc", "value": str(sheet_count), "sub": sheet_sub, "class": "health"},
        {"label": "Bản ghi đã kiểm tra", "value": str(total_records), "sub": "live workbook", "class": "health"},
        {"label": "Lỗi schema", "value": "0" if audit.core_complete else str(len(audit.missing_sheets)), "sub": "schema errors", "class": "health"},
        {"label": "Input hash", "value": f"{workbook_hash[:4]}…", "sub": "đối soát nguồn", "class": "health"},
    ]
    period_rows = filtered_cashflow_rows()
    breach_count = sum(bool(item.breach) for item in period_rows)
    worst = max(period_rows, key=lambda item: item.funding_need_vnd) if period_rows else None
    margin = margin_for_contract(contract_id)
    gross_margin = margin.get("gross_margin")
    target_margin = margin.get("target_margin", 0.28)
    credits = related_credit_cases(contract_id)
    risks = execution_risks_for_contract(contract_id)
    status, reason = contract_status(contract_id)
    contract_row = selected_contract_row(contract_id)
    contract_value = margin.get("contract_value_vnd", contract_row.get("contract_value"))
    txn_amount = risk.transaction_hold_amount_vnd if contract_id == "CON-004" else 0
    approved_count = sum(
        st.session_state[key] == "approved"
        for key in ("ap1_status", "ap2_status", "ap3_status", "ap4_status")
    )
    if agent_focus == "Finance & Data":
        cards.extend(
            [
                {"label": "Cash reserve breach", "value": f"{breach_count}/{len(period_rows)} tháng", "sub": selected_period, "class": "warn"},
                {"label": "Funding gap lớn nhất", "value": money(worst.funding_need_vnd if worst else None), "sub": worst.month if worst else "không có dữ liệu", "class": "warn"},
                {"label": f"Giá trị {contract_id}", "value": money(contract_value), "sub": "contract scope", "class": ""},
                {"label": f"Gross margin {contract_id}", "value": f"{float(gross_margin) * 100:.1f}%" if gross_margin is not None and pd.notna(gross_margin) else "n/a", "sub": f"ngưỡng {float(target_margin) * 100:.1f}%", "class": "danger" if gross_margin is not None and pd.notna(gross_margin) and float(gross_margin) < float(target_margin) else ""},
            ]
        )
    elif agent_focus == "Risk & Compliance":
        cards.extend(
            [
                {"label": "Cụm giao dịch Critical", "value": money(txn_amount), "sub": contract_id, "class": "danger" if txn_amount else ""},
                {"label": "Execution risk", "value": str(len(risks)), "sub": "rủi ro theo hợp đồng", "class": "danger" if risks else ""},
                {"label": "Credit case bị giữ", "value": str(sum(str(item.get("candidate_status", "")).lower() == "hold" for item in credit_df.to_dict("records"))), "sub": "thiếu bằng chứng / dưới ngưỡng", "class": "warn"},
                {"label": "Data divergence", "value": str(backend.risk.data_health.divergence_count), "sub": "đã gắn resolver", "class": "warn"},
            ]
        )
    elif agent_focus == "Decision & Partner":
        cards.extend(
            [
                {"label": "Credit case liên quan", "value": str(len(credits)), "sub": contract_id, "class": ""},
                {"label": "Gói vốn đề xuất", "value": money(finance.decision_package_total_ask_vnd), "sub": "CR-001 + CR-002", "class": "warn"},
                {"label": "Approval hoàn tất", "value": f"{approved_count}/4", "sub": "trước quyết định cuối", "class": ""},
                {"label": "Khuyến nghị", "value": recommendation_for_contract(contract_id)[0], "sub": current_stage(decision_card["state"]) if contract_id == "CON-004" else "ANALYZED", "class": ""},
            ]
        )
    elif selected_contract != "Tất cả hợp đồng":
        cards.extend(
            [
                {"label": "Portfolio cash reserve breach", "value": f"{breach_count}/{len(period_rows)} tháng", "sub": selected_period, "class": "warn"},
                {"label": "Portfolio funding gap lớn nhất", "value": money(worst.funding_need_vnd if worst else None), "sub": worst.month if worst else "không có dữ liệu", "class": "warn"},
                {"label": f"Gross margin {contract_id}", "value": f"{float(gross_margin) * 100:.1f}%" if gross_margin is not None and pd.notna(gross_margin) else "n/a", "sub": f"{money(contract_value)} · ngưỡng {float(target_margin) * 100:.1f}%", "class": "danger" if gross_margin is not None and pd.notna(gross_margin) and float(gross_margin) < float(target_margin) else ""},
                {"label": "Mức ưu tiên", "value": status, "sub": reason, "class": "danger" if status == "CRITICAL" else "warn" if status in {"HIGH", "WATCH"} else ""},
            ]
        )
    else:
        cards.extend(
            [
                {"label": "Cash reserve breach", "value": f"{breach_count}/{len(period_rows)} tháng", "sub": selected_period, "class": "warn"},
                {"label": "Funding gap lớn nhất", "value": money(worst.funding_need_vnd if worst else None), "sub": worst.month if worst else "không có dữ liệu", "class": "warn"},
                {"label": "TXN cluster flagged", "value": money(risk.transaction_hold_amount_vnd), "sub": "portfolio", "class": "danger"},
                {"label": "Credit case đang mở", "value": str(len(credit_df)), "sub": "portfolio", "class": ""},
            ]
        )
    return cards


def render_stage_approval_controls() -> None:
    ap1_done = st.session_state.ap1_status == "approved"
    ap2_done = st.session_state.ap2_status == "approved"
    ap3_done = st.session_state.ap3_status == "approved"
    ap4_done = st.session_state.ap4_status == "approved"
    ap23_done = ap1_done and ap2_done and ap3_done

    if ap4_done:
        return

    st.markdown("#### Hàng chờ phê duyệt")
    if not ap1_done:
        info, action = st.columns([0.75, 0.25], vertical_alignment="center")
        info.markdown(
            f"**AP-1 · Tạm giữ TXN-006/007**  \n{money(risk.transaction_hold_amount_vnd)} · mở khóa Decision Card"
        )
        if action.button(
            "Duyệt AP-1",
            type="primary",
            width="stretch",
            key="approve_ap1",
        ):
            st.session_state.ap1_status = "approved"
            st.session_state.final_state = "CREDIT_PACKAGE_PROPOSED"
            st.session_state.human_approval_id = "APR-001"
            st.session_state.action_warning = None
            st.session_state.action_toast = "Đã duyệt AP-1 và mở khóa luồng quyết định."
            st.rerun()
        return

    approval_items = [
        (
            "AP-2 · Vốn lưu động CR-001",
            "950 triệu VND",
            "approve_ap2",
            ap2_done,
            False,
        ),
        (
            "AP-3 · Bảo lãnh thực hiện CR-002",
            "420 triệu VND",
            "approve_ap3",
            ap3_done,
            False,
        ),
        (
            "AP-4 · Gửi hồ sơ đã masking",
            "mở Bank API sandbox",
            "approve_ap4",
            ap4_done,
            not ap23_done,
        ),
    ]
    for title, subtitle, key, done, blocked_item in approval_items:
        info, action = st.columns([0.75, 0.25], vertical_alignment="center")
        info.markdown(f"**{title}**  \n{subtitle}")
        approval_id = key.removeprefix("approve_").upper().replace("AP", "AP-")
        if action.button(
            "Đã duyệt" if done else f"Duyệt {approval_id}",
            width="stretch",
            disabled=done or blocked_item,
            key=key,
        ):
            if key == "approve_ap2":
                st.session_state.ap2_status = "approved"
                st.session_state.human_approval_id = "APR-002"
                st.session_state.action_toast = "Đã duyệt AP-2 vốn lưu động."
            elif key == "approve_ap3":
                st.session_state.ap3_status = "approved"
                st.session_state.human_approval_id = "APR-003"
                st.session_state.action_toast = "Đã duyệt AP-3 bảo lãnh thực hiện."
            else:
                st.session_state.ap4_status = "approved"
                st.session_state.final_state = "DECISION_READY"
                st.session_state.human_approval_id = "APR-004"
                st.session_state.action_toast = "Đã duyệt AP-4. Bank API sandbox đã được mở."
            st.session_state.action_warning = None
            st.rerun()
    if not ap23_done:
        st.caption("AP-4 chỉ mở sau khi AP-2 và AP-3 cùng hoàn tất.")


def render_hold_card() -> None:
    st.markdown(
        '<div class="hold-card"><strong>CR-003 · trade finance — HOLD</strong><br>'
        'Eligibility 0.56 · Supplier confirmation: MISSING. '
        'Không ảnh hưởng CR-001/CR-002 trong gói chính.</div>',
        unsafe_allow_html=True,
    )


def render_final_decision_controls() -> None:
    all_prereq_done = (
        st.session_state.ap1_status == "approved"
        and st.session_state.ap2_status == "approved"
        and st.session_state.ap3_status == "approved"
        and st.session_state.ap4_status == "approved"
    )
    if st.session_state.action_warning:
        st.warning(st.session_state.action_warning)
    if not all_prereq_done:
        st.caption("Quyết định cuối và Bank API chỉ xuất hiện sau khi AP-1 đến AP-4 hoàn tất.")
        return
    if st.session_state.final_state == "ACTIVE":
        st.markdown(
            f'<div class="state-box state-ok mono">state: ACTIVE · human_approval_id: '
            f'{esc(st.session_state.human_approval_id)}<br>ACTIVE — hợp đồng được kích hoạt</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown("##### AP-5 · Quyết định cuối")
    actions = st.columns(4)
    if actions[0].button("Phê duyệt", type="primary", width="stretch", key="final_approve"):
        st.session_state.final_state = "ACTIVE"
        st.session_state.human_approval_id = "APR-FINAL-APPROVE"
        st.session_state.action_warning = None
        st.session_state.action_toast = "Đã duyệt gói đề xuất."
        st.rerun()
    if actions[1].button("Từ chối", width="stretch", key="final_reject"):
        st.session_state.final_state = "REJECTED"
        st.session_state.human_approval_id = "APR-FINAL-REJECT"
        st.session_state.action_warning = None
        st.session_state.action_toast = "Đã ghi nhận quyết định từ chối."
        st.rerun()
    if actions[2].button("Yêu cầu thêm thông tin", width="stretch", key="final_need_info"):
        st.session_state.final_state = "NEED_MORE_INFORMATION"
        st.session_state.human_approval_id = "APR-NEEDINFO-001"
        st.session_state.action_warning = None
        st.session_state.action_toast = "Đã yêu cầu bổ sung thông tin."
        st.rerun()
    if actions[3].button("Đàm phán lại", width="stretch", key="final_renegotiate"):
        st.session_state.final_state = "RENEGOTIATE"
        st.session_state.human_approval_id = "APR-FINAL-RENEGOTIATE"
        st.session_state.action_warning = None
        st.session_state.action_toast = "Đã chuyển hồ sơ sang đàm phán lại."
        st.rerun()


if page == "Tổng quan":
    render_snapshot_panel(snapshot_cards_for_view(detail_contract_id))
    with st.container(border=True):
        zone_heading("PORTFOLIO", "Dữ liệu chi tiết theo bộ lọc")
        st.markdown(
            f'<div class="next-step"><div class="next-step-label">Cách đọc màn hình</div>Các KPI phía trên đang theo phạm vi <strong>{esc(selected_contract)}</strong>, kỳ <strong>{esc(selected_period)}</strong> và <strong>{esc(agent_focus)}</strong>. Đổi filter sẽ cập nhật số liệu hoặc phạm vi hiển thị, không thay đổi dữ liệu nguồn.</div>',
            unsafe_allow_html=True,
        )
        tab_contracts, tab_credit, tab_source = st.tabs(["Hợp đồng", "Credit case", "Nguồn dữ liệu"])
        with tab_contracts:
            summary = contract_summary_table()
            visible_summary = summary[[col for col in ["contract_id", "status", "contract_value_vnd", "gross_margin", "agent_priority", "reason"] if col in summary.columns]]
            st.dataframe(visible_summary, width="stretch", hide_index=True)
            st.caption(f"Đang hiển thị {len(summary)}/{len(contract_ids)} hợp đồng. Customer ID đã được token hóa ở lớp dữ liệu.")
        with tab_credit:
            credit_show = _tokenize_df(credit_df, ["company_id", "customer_id"])
            if not credit_show.empty and selected_contract != "Tất cả hợp đồng":
                credit_show = related_credit_cases(selected_contract)
            credit_cols = [col for col in ["credit_case_id", "request_type", "requested_amount_vnd", "eligibility_score", "precheck_note", "approval_status"] if col in credit_show.columns]
            st.dataframe(credit_show[credit_cols], width="stretch", hide_index=True)
            st.caption("CR-003 bị giữ vì thiếu supplier confirmation; CR-001/CR-002 là gói chính cần Founder approval.")
        with tab_source:
            audit = backend.finance.source_audit
            source_rows = pd.DataFrame([{"sheet": key, "records": value} for key, value in audit.row_counts.items()])
            st.dataframe(source_rows, width="stretch", hide_index=True)
            st.caption("Tổng 14 sheet đã nạp; các agent dùng chung một phần nguồn nên tổng theo agent không cộng trực tiếp.")

elif page == "Chi tiết hợp đồng":
    contract_row = selected_contract_row(detail_contract_id)
    order_rows = related_orders(detail_contract_id)
    invoice_rows = related_invoices(order_rows)
    margin = margin_for_contract(detail_contract_id)
    exec_risks = execution_risks_for_contract(detail_contract_id)
    contract_rec, contract_rationale = recommendation_for_contract(detail_contract_id)
    detail_state = (
        decision_card["state"]
        if detail_contract_id == "CON-004"
        else contract_status(detail_contract_id)[0]
    )
    blocked = (
        detail_contract_id == "CON-004"
        and st.session_state.ap1_status != "approved"
        and risk.financial_flow_paused
    )

    render_snapshot_panel(snapshot_cards_for_view(detail_contract_id))
    main_col, evidence_col = st.columns([0.76, 0.24], gap="medium")

    with main_col:
        with st.container(border=True):
            zone_heading("ZONE 2", "Contract Detail — Decision & Approval Flow")
            render_stepper(detail_state)
            render_contract_heading(detail_contract_id, contract_row, detail_state)
            if selected_contract == "Tất cả hợp đồng":
                st.info(
                    f"Portfolio đang được chọn; màn chi tiết mở {detail_contract_id} làm case demo mặc định. "
                    "Chọn một hợp đồng trong sidebar để chuyển phạm vi."
                )

            if blocked:
                st.markdown(
                    f'''<div class="state-box">
                        <div style="display:flex;gap:10px;align-items:flex-start">
                            <img src="{WARNING_URI}" alt="Cảnh báo" style="width:18px;height:18px;object-fit:contain;margin-top:1px" />
                            <div><strong>BLOCKED BY CRITICAL RISK</strong><br>
                            TXN-006/007 · {esc(money(risk.transaction_hold_amount_vnd))} · risk score ≥ 85.
                            Luồng tài chính tạm dừng cho đến khi Founder xử lý AP-1.</div>
                        </div>
                    </div>''',
                    unsafe_allow_html=True,
                )
            agent_left, agent_right = st.columns(2, gap="medium")
            with agent_left:
                if agent_visible("Finance & Data"):
                    with st.container(border=True):
                        st.markdown("##### Finance & Data Agent")
                        contract_value = margin.get("contract_value_vnd", contract_row.get("contract_value"))
                        gross_margin = margin.get("gross_margin")
                        target_margin = margin.get("target_margin", 0.28)
                        period_rows = filtered_cashflow_rows()
                        worst_period = max(period_rows, key=lambda item: item.funding_need_vnd) if period_rows else None
                        gross_margin_text = (
                            f"{float(gross_margin) * 100:.1f}%"
                            if gross_margin is not None and pd.notna(gross_margin)
                            else "không rõ"
                        )
                        if detail_contract_id == "CON-004":
                            st.markdown(
                                f'''<div class="agent-brief">
                                <div class="agent-brief-row">Funding gap {esc(worst_period.month if worst_period else selected_period)}: <strong>{esc(money(worst_period.funding_need_vnd) if worst_period else "không có dữ liệu")}</strong></div>
                                <div class="agent-brief-row">Margin warning: {esc(gross_margin_text)} &lt; ngưỡng {float(target_margin) * 100:.1f}% — rà soát giá/cost trước khi ký · RR-003</div>
                                <div class="agent-brief-row">Credit candidates: CR-004 (0.78) → CR-001 (0.71) → CR-002 (0.63) → CR-003 (0.56)</div>
                                </div>''',
                                unsafe_allow_html=True,
                            )
                        else:
                            finance_cols = st.columns(2)
                            with finance_cols[0]:
                                metric_card("Giá trị hợp đồng", money(contract_value), None, "blue")
                            with finance_cols[1]:
                                metric_card(
                                    "Gross margin",
                                    gross_margin_text,
                                    f"ngưỡng {float(target_margin) * 100:.1f}%",
                                    "green",
                                )
                else:
                    st.caption("Finance & Data Agent đang được ẩn bởi filter.")

            with agent_right:
                if agent_visible("Risk & Compliance"):
                    with st.container(border=True):
                        st.markdown("##### Risk & Compliance Agent")
                        has_transaction_risk = detail_contract_id == "CON-004" and bool(risk.transaction_hold_amount_vnd)
                        if detail_contract_id == "CON-004":
                            execution_line = "ORD-004 (CON-003) at risk — penalty 4.65 triệu/ngày nếu delay > 7 ngày · RR-007"
                            st.markdown(
                                f'''<div class="agent-brief">
                                <div class="agent-brief-row"><span class="critical">TXN-006/007 cluster — exposure {esc(money(risk.transaction_hold_amount_vnd))} — Critical</span> · RR-001</div>
                                <div class="agent-brief-row">{esc(execution_line)}</div>
                                <div class="agent-brief-row">CR-003: evidence thiếu supplier confirmation → Hold · RR-006</div>
                                </div>''',
                                unsafe_allow_html=True,
                            )
                        elif exec_risks:
                            risk_table = pd.DataFrame(exec_risks)
                            risk_cols = [
                                col
                                for col in [
                                    "order_id",
                                    "status",
                                    "potential_penalty_vnd_per_day",
                                    "severity",
                                    "rule_id",
                                ]
                                if col in risk_table.columns
                            ]
                            st.dataframe(
                                risk_table[risk_cols],
                                width="stretch",
                                hide_index=True,
                            )
                        else:
                            st.success("Không có transaction hoặc execution risk mở trong phạm vi hợp đồng.")
                else:
                    st.caption("Risk & Compliance Agent đang được ẩn bởi filter.")

            if detail_contract_id == "CON-004":
                render_stage_approval_controls()

                if blocked:
                    render_hold_card()
                else:
                    render_decision_card(decision_card)
                    render_final_decision_controls()
                    render_hold_card()

            if agent_visible("Decision & Partner"):
                with st.expander("Decision & Partner Agent · bằng chứng bổ sung", expanded=False):
                    cases = related_credit_cases(detail_contract_id)
                    if blocked:
                        st.info(
                            "Decision & Partner đang chờ AP-1. Chưa hiển thị bảng candidate hoặc nội dung OpenAI trước khi Founder xác nhận tạm giữ."
                        )
                    elif cases.empty:
                        st.info("Workbook chưa có credit case chuyên biệt cho hợp đồng này.")
                    else:
                        top_case = cases.sort_values(
                            "eligibility_score",
                            ascending=False,
                            na_position="last",
                        ).iloc[0]
                        info_card(
                            "Hướng dẫn hành động",
                            f"{top_case.get('credit_case_id', 'Credit case')} đang có eligibility cao nhất "
                            f"({float(top_case.get('eligibility_score', 0)):.2f}). "
                            "So sánh requested amount, eligibility và precheck note; không dùng một mình eligibility để quyết định.",
                        )
                        case_cols = [
                            col
                            for col in [
                                "credit_case_id",
                                "request_type",
                                "requested_amount_vnd",
                                "eligibility_score",
                                "precheck_note",
                            ]
                            if col in cases.columns
                        ]
                        st.dataframe(cases[case_cols], width="stretch", hide_index=True)
                    if detail_contract_id == "CON-004" and not blocked:
                        info_card(
                            "Bank fit matrix",
                            "CR-004 là bridge nhỏ có eligibility cao; CR-001/CR-002 là gói chính cần Founder approval; "
                            "CR-003 tiếp tục giữ vì thiếu supplier confirmation.",
                        )
                        fit_df = pd.DataFrame(decision_card["bank_fit_matrix"])
                        fit_cols = [
                            col
                            for col in [
                                "credit_case_id",
                                "bank_product_id",
                                "fit_status",
                                "collateral_vnd",
                                "collateral_basis",
                            ]
                            if col in fit_df.columns
                        ]
                        st.dataframe(fit_df[fit_cols], width="stretch", hide_index=True)
                        st.json(decision_card.get("llm_meta", {}), expanded=False)
                    elif detail_contract_id != "CON-004":
                        st.caption(
                            "Phạm vi đã kiểm chứng: Decision Card sâu và AP-1 đến AP-5 được thiết kế cho CON-004; "
                            "hợp đồng này hiển thị Finance/Risk precheck và credit evidence có trong workbook."
                        )

            with st.expander("Dữ liệu hợp đồng đã token hóa", expanded=False):
                safe_contract_row = _tokenize_record(contract_row, ["customer_id"])
                st.json(
                    {
                        "contract_id": detail_contract_id,
                        "customer": selected_customer_name(contract_row),
                        **safe_contract_row,
                    },
                    expanded=False,
                )
                source_tab1, source_tab2, source_tab3 = st.tabs(
                    ["Orders", "Invoices", "Giao dịch bị flag"]
                )
                with source_tab1:
                    st.dataframe(order_rows, width="stretch", hide_index=True)
                with source_tab2:
                    st.dataframe(
                        _tokenize_df(invoice_rows, ["customer_id"]),
                        width="stretch",
                        hide_index=True,
                    )
                with source_tab3:
                    flagged = pd.DataFrame(
                        [item.model_dump() for item in backend.risk.transaction_findings]
                    )
                    st.dataframe(flagged, width="stretch", hide_index=True)

            if detail_contract_id != "CON-004":
                st.markdown("---")
                st.markdown("#### Hỗ trợ quyết định")
                st.markdown(
                    f'<div class="next-step"><div class="next-step-label">Actionable next step cho Founder</div>{esc(founder_next_step())}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'''<div class="decision-card">
                        <div class="decision-head">
                            <div><div class="decision-kicker">Contract Precheck</div>
                            <div class="decision-state">state: {esc(detail_state)}</div></div>
                            <div class="decision-rec">{esc(contract_rec)}</div>
                        </div>
                        <div style="padding:14px;color:#374151;font-size:12.5px">{esc(contract_rationale)}</div>
                    </div>''',
                    unsafe_allow_html=True,
                )

            cash_tab, credit_tab = st.tabs(["Dòng tiền", "Gói tín dụng"])
            with cash_tab:
                cash_rows = filtered_cashflow_rows()
                cash = pd.DataFrame([item.model_dump() for item in cash_rows])
                if not cash.empty:
                    st.line_chart(
                        cash.set_index("month")[["funding_need_vnd", "reserve_gap_vnd"]]
                    )
                    worst_cash = max(cash_rows, key=lambda item: item.funding_need_vnd)
                    recovery_month = decision_card.get("upside_if_conditions_met", {}).get(
                        "recovery_month", "chưa xác định"
                    )
                    info_card(
                        "Actionable cashflow insight",
                        f"Funding need đạt đỉnh {money(worst_cash.funding_need_vnd)} vào {worst_cash.month}. "
                        f"Founder nên chốt nguồn vốn trước tháng này; mô hình kỳ vọng phục hồi ở {recovery_month}.",
                    )
                else:
                    st.info("Không có dữ liệu dòng tiền trong phạm vi kỳ đã chọn.")
            with credit_tab:
                cases = related_credit_cases(detail_contract_id)
                credit_cols = [
                    col
                    for col in [
                        "credit_case_id",
                        "request_type",
                        "requested_amount_vnd",
                        "eligibility_score",
                        "precheck_note",
                    ]
                    if col in cases.columns
                ]
                st.dataframe(cases[credit_cols], width="stretch", hide_index=True)
                if detail_contract_id == "CON-004":
                    info_card(
                        "Actionable credit insight",
                        f"Gói chính CR-001 + CR-002 cần {money(decision_card['financial_ask']['total'])}; "
                        "CR-001 tài trợ vốn lưu động, CR-002 hỗ trợ bảo lãnh thực hiện. "
                        "CR-003 chưa được đưa vào gói vì thiếu supplier confirmation.",
                    )
                    if not blocked:
                        credit_metrics = st.columns(2)
                        credit_metrics[0].metric(
                            "Nhu cầu vốn",
                            money(decision_card["financial_ask"]["total"]),
                        )
                        credit_metrics[1].metric(
                            "Tài sản đảm bảo",
                            money(decision_card["financial_ask"]["collateral_total"]),
                        )

            st.markdown("---")
            if detail_contract_id != "CON-004":
                st.info(
                    "CON-004 là case được kiểm chứng end-to-end theo yêu cầu demo. "
                    "Hợp đồng hiện tại giữ ở precheck vì workbook chưa có approval workflow riêng."
                )
            else:
                if st.session_state.ap4_status == "approved":
                    st.markdown("#### Bank API sandbox")
                    candidate_by_id = {
                        item.credit_case_id: item
                        for item in backend.finance.credit_candidates
                    }
                    package_ids = (
                        backend.finance.credit_plan.decision_package_credit_case_ids
                        if backend.finance.credit_plan
                        else list(candidate_by_id)
                    )
                    api_case_ids = [
                        credit_case_id
                        for credit_case_id in package_ids
                        if credit_case_id in CREDIT_TO_API
                    ]
                    selected_api_case = st.selectbox(
                        "Gói tín dụng cần precheck",
                        api_case_ids,
                        key="bank_api_credit_case",
                    )
                    selected_api_id = CREDIT_TO_API[selected_api_case]
                    catalog_row = next(
                        (
                            row
                            for row in team_pack.get("12_API_CATALOG", [])
                            if str(row.get("api_id")) == selected_api_id
                        ),
                        {},
                    )
                    st.caption(
                        f"{selected_api_id} · {catalog_row.get('method', 'POST')} "
                        f"{catalog_row.get('endpoint', 'endpoint chưa khai báo')} · sandbox, không gửi ngân hàng thật"
                    )
                    scenario_status = 200
                    with st.expander("Chế độ kiểm thử lỗi kỹ thuật", expanded=False):
                        scenario_map = {
                            "Thành công": 200,
                            "Dữ liệu đầu vào không hợp lệ": 400,
                            "Xác thực sandbox thất bại": 401,
                            "Hồ sơ trùng hoặc xung đột": 409,
                            "Vượt giới hạn gọi thử": 429,
                            "Dịch vụ sandbox tạm thời gián đoạn": 503,
                        }
                        scenario_label = st.selectbox(
                            "Kịch bản phản hồi",
                            list(scenario_map),
                            key="bank_api_test_scenario",
                        )
                        scenario_status = scenario_map[scenario_label]
                        st.caption(
                            "Khu vực này phục vụ giám khảo/tester kiểm tra safe failure; Founder không cần chọn mã HTTP."
                        )
                    if st.button(
                        "Gọi Bank API mock",
                        type="primary",
                        width="stretch",
                        key="call_bank_api",
                    ):
                        candidate = candidate_by_id[selected_api_case]
                        st.session_state.bank_api_response = call_bank_api_mock(
                            selected_api_case,
                            candidate.requested_amount_vnd,
                            scenario_status,
                            api_catalog=team_pack.get("12_API_CATALOG", []),
                            sandbox_contracts=team_pack.get("22_SANDBOX_CONTRACT", []),
                        )
                        result = st.session_state.bank_api_response
                        if result["ok"]:
                            st.toast(f"{selected_api_id}: sandbox pre-check thành công.")
                        else:
                            st.toast(f"{selected_api_id}: safe failure đã được ghi nhận.")
                    if st.session_state.bank_api_response:
                        api_result = st.session_state.bank_api_response
                        if api_result["ok"]:
                            st.success(
                                "Sandbox pre-check thành công; hồ sơ vẫn cần phê duyệt con người trước khi submit."
                            )
                        else:
                            st.warning(
                                f"Safe failure: {api_result.get('required_handling')}"
                            )
                        with st.expander("Chi tiết phản hồi kỹ thuật", expanded=False):
                            st.json(api_result, expanded=False)

                if st.button(
                    "Xuất runtime log mẫu",
                    width="stretch",
                    key="export_runtime_log",
                ):
                    log_path = write_json(
                        ROOT / "runtime_logs" / "sample_runtime_log.json",
                        build_sample_runtime_log(decision_card),
                    )
                    card_path = write_json(
                        ROOT / "output" / "demo_decision_card.json",
                        decision_card,
                    )
                    st.success(f"Đã xuất {log_path.name} và {card_path.name}")

    with evidence_col:
        with st.container(border=True):
            zone_heading("ZONE 3", "System Evidence")
            render_runtime_evidence(decision_card)
            st.markdown(
                '<div class="mono" style="font-size:10px;color:#596273;margin:2px 0 6px">OpenAI Evidence</div>',
                unsafe_allow_html=True,
            )
            render_openai_evidence(decision_card)
            with st.expander("Bằng chứng kỹ thuật", expanded=False):
                st.json(
                    {
                        "trace_id": decision_card.get("trace_id"),
                        "decision_version": decision_card.get("decision_version"),
                        "human_approval_id": decision_card.get("human_approval_id"),
                        "masked_fields": decision_card.get("masked_fields"),
                    },
                    expanded=False,
                )
else:
    render_snapshot_panel(snapshot_cards_for_view(detail_contract_id), "Data Health & Audit Evidence")
    safe_backend_evidence = {
        "finance_handoff": finance.model_dump(mode="json"),
        "risk_handoff": risk.model_dump(mode="json"),
        "finance_source_audit": backend.finance.source_audit.model_dump(mode="json") if backend.finance.source_audit else None,
        "risk_rule_snapshot": backend.risk.rule_snapshot.model_dump(mode="json") if backend.risk.rule_snapshot else None,
        "contracts": contract_summary_table().to_dict(orient="records"),
        "credit_cases": _tokenize_df(
            credit_df,
            ["company_id", "customer_id"],
        ).to_dict(orient="records"),
    }
    with st.container(border=True):
        zone_heading("ZONE 3", "System Evidence")
        st.markdown(
            '<div class="next-step"><div class="next-step-label">Trust & explainability</div>'
            'Số liệu, threshold và trạng thái approval là deterministic. OpenAI chỉ sinh conflict summary, conditions và rationale; '
            'mọi output đều qua schema validation và có deterministic fallback.</div>',
            unsafe_allow_html=True,
        )
        ev1, ev2, ev3 = st.columns(3)
        ev1.metric("Trace", decision_card.get("trace_id", "n/a"))
        ev2.metric("Schema", decision_card.get("llm_meta", {}).get("schema_validation", "NOT_RUN"))
        ev3.metric("OpenAI mode", openai_label)
        with st.expander("Finance/Risk handoff và nguồn audit", expanded=False):
            st.json(safe_backend_evidence, expanded=False)
        with st.expander("OpenAI runtime và fallback policy", expanded=False):
            st.json(
                {
                    "where_used": "Decision & Partner Agent - conflict summary, conditions, rationale",
                    "deterministic_inputs": ["finance_handoff", "risk_handoff", "bank_fit_matrix"],
                    "generated_outputs": ["conflicts_detected", "conditions", "rationale"],
                    "mode_runtime": decision_card.get("llm_meta", {}),
                    "fallback_policy": (
                        "Có OPENAI_API_KEY thì gọi GPT-4o live; thiếu key/API lỗi thì dùng deterministic fallback; "
                        "output sai schema bị từ chối và ghi trạng thái failure."
                    ),
                },
                expanded=False,
            )
        with st.expander("Decision Card CON-004", expanded=False):
            st.json(decision_card, expanded=False)
        with st.expander("Runtime log", expanded=False):
            st.json(build_sample_runtime_log(decision_card), expanded=False)



