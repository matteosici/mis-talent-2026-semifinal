from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import time
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
from src.founder_insights import (
    build_founder_insights,
    founder_insight_signature,
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
.approval-progress { border:1px solid #d8ddd4; border-radius:9px; padding:11px 13px 12px; margin:0 0 14px; background:#f8faf7; }
.approval-progress-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; }
.approval-progress-title { color:var(--ink); font-size:11.5px; font-weight:850; }
.approval-progress-count { color:#596273; font:700 9.5px "IBM Plex Mono",Consolas,monospace; white-space:nowrap; }
.approval-progress-track { height:5px; border-radius:999px; background:#e2e5df; overflow:hidden; margin-bottom:9px; }
.approval-progress-fill { height:100%; border-radius:inherit; background:var(--green); transition:width .25s ease; }
.approval-progress-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:7px; }
.approval-stage { border:1px solid #dde1da; border-radius:7px; padding:7px 8px; background:#fff; min-width:0; }
.approval-stage.complete { border-color:#c2decf; background:var(--green-soft); }
.approval-stage.waiting { border-color:#dfc589; background:var(--amber-soft); }
.approval-stage-id { color:var(--ink); font:800 9.5px "IBM Plex Mono",Consolas,monospace; }
.approval-stage-status { color:#737b8d; font-size:9.5px; margin-top:3px; overflow-wrap:anywhere; }
.approval-stage.complete .approval-stage-id, .approval-stage.complete .approval-stage-status { color:var(--green); }
.approval-stage.waiting .approval-stage-id, .approval-stage.waiting .approval-stage-status { color:var(--amber); }
.state-box { border:1px solid #f1b7b1; padding:13px 14px; background:var(--red-soft); border-radius:8px; margin-bottom:12px; color:#8f2f29; }
.state-ok { border-color:#bddccb; background:var(--green-soft); color:var(--green); }
.blocker-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px; }
.blocker-kicker { font:800 9.5px "IBM Plex Mono",Consolas,monospace; letter-spacing:.05em; text-transform:uppercase; }
.blocker-title { color:#7f241f; font-size:14px; font-weight:900; line-height:1.3; margin-bottom:6px; }
.blocker-copy { color:#7e332e; font-size:12px; line-height:1.5; }
.blocker-action { margin-top:9px; border-top:1px solid #efc4bf; padding-top:8px; color:#6f2924; font-size:12px; line-height:1.45; }
.insight-source { display:inline-flex; align-items:center; border-radius:999px; padding:4px 7px; background:#fff; color:#6d5a7f; border:1px solid #decfed; font:750 8.5px "IBM Plex Mono",Consolas,monospace; white-space:nowrap; }
.analysis-overview-title { display:flex; align-items:center; justify-content:space-between; gap:10px; border-left:4px solid var(--purple); background:#f9f7fc; border-radius:7px; padding:9px 11px; margin:2px 0 10px; color:var(--ink); font-size:12px; font-weight:850; }
.agent-insight-list { margin:0; padding:0; list-style:none; color:#30384a; font-size:11.5px; line-height:1.45; }
.agent-insight-list > li { border-bottom:1px solid #e3e6e1; padding:7px 0; }
.agent-insight-list > li:last-child { border-bottom:0; }
.agent-insight-list strong { color:var(--ink); }
.credit-priority-list { margin:6px 0 0 18px; padding:0; color:#596273; font-size:10px; }
.credit-priority-list li { padding:2px 0; }
.agent-kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(112px,1fr)); gap:7px; width:100%; max-width:100%; min-width:0; margin:0 0 10px; padding:0 0 8px; }
.agent-kpi-card { border:1px solid #dbe0d8; border-radius:7px; padding:8px; width:100%; max-width:100%; min-width:0; overflow:hidden; background:#f8faf7; }
.agent-kpi-card.danger { border-color:#efc4bf; background:#fff5f2; }
.agent-kpi-label { color:#697386; font-size:8.5px; line-height:1.25; min-height:22px; min-width:0; overflow-wrap:anywhere; }
.agent-kpi-value { color:var(--ink); font-size:clamp(11.5px,1.1vw,13.5px); font-weight:900; line-height:1.18; margin-top:5px; max-width:100%; overflow-wrap:anywhere; word-break:normal; }
.agent-kpi-note { color:#71798a; font:8px "IBM Plex Mono",Consolas,monospace; line-height:1.3; margin-top:4px; max-width:100%; white-space:normal; overflow-wrap:anywhere; }
.founder-insight-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:12px 0 16px; }
.founder-insight-card { background:#fff7db; border:1px solid #e6b84d; border-left:5px solid #d99a2b; border-radius:8px; padding:14px 16px; min-width:0; }
.founder-insight-label { color:#7a4f00; font:800 10px "IBM Plex Mono",Consolas,monospace; letter-spacing:.04em; text-transform:uppercase; margin-bottom:6px; }
.founder-insight-main { color:#2f2412; font-size:15px; line-height:1.45; font-weight:750; }
.founder-insight-next { color:#5c3d00; font-size:12px; line-height:1.45; margin-top:8px; padding-top:8px; border-top:1px solid rgba(135,85,0,.2); }
.partner-card { border:1px solid #cfb9e5; border-left:5px solid var(--purple); background:#fbf8ff; border-radius:9px; padding:14px 16px; margin:10px 0 14px; }
.partner-card-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:7px; }
.partner-card-title { color:var(--ink); font-size:14px; font-weight:900; }
.partner-card-state { border-radius:999px; padding:4px 8px; background:#efe5fa; color:#69399a; font:800 8.5px "IBM Plex Mono",Consolas,monospace; white-space:nowrap; }
.partner-card-body { color:#41495b; font-size:12.5px; line-height:1.5; }
.partner-card-next { color:#4f2b78; font-size:11.5px; line-height:1.45; font-weight:750; margin-top:8px; }
.gate-kpi-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:6px 0 13px; }
.gate-kpi-card { border:1px solid #dbe0d8; border-radius:8px; padding:10px 11px; background:#fff; min-width:0; }
.gate-kpi-card.danger { border-color:#efc4bf; background:#fff5f2; }
.gate-kpi-label { color:#697386; font-size:9.5px; font-weight:800; line-height:1.25; }
.gate-kpi-value { color:var(--ink); font-size:14px; font-weight:900; line-height:1.22; margin-top:5px; overflow-wrap:anywhere; }
.gate-kpi-note { color:#71798a; font:8.5px "IBM Plex Mono",Consolas,monospace; line-height:1.35; margin-top:5px; }
.sandbox-box { border:1px solid #d7dbe3; border-radius:9px; padding:12px 13px; background:#fbfcfa; margin:12px 0 14px; }
.sandbox-box.locked { background:#f8fafc; color:#596273; }
.sandbox-title { color:var(--ink); font-size:13px; font-weight:900; margin-bottom:5px; }
.sandbox-copy { color:#596273; font-size:11.5px; line-height:1.45; }
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
.financial-main { display:flex; align-items:center; gap:7px; flex-wrap:wrap; color:var(--ink); font-weight:800; }
.financial-sub { color:#697386; font-size:10.5px; line-height:1.4; margin-top:3px; }
.approval-pill, .severity-pill { display:inline-flex; align-items:center; border-radius:999px; padding:3px 7px; font:800 8.5px "IBM Plex Mono",Consolas,monospace; white-space:nowrap; }
.approval-pill.approved { background:#d9eee4; color:#1f6b51; }
.approval-pill.pending { background:#fff0cf; color:#875500; }
.approval-pill.locked { background:#eceee9; color:#737b8d; }
.approval-pill.rejected { background:#fde2df; color:#9a2d27; }
.decision-total { font-size:17px; font-weight:850; color:var(--ink); }
.decision-note { padding:9px 10px; border-radius:7px; background:#faf8fc; color:#3b4253; font-size:11.5px; margin-bottom:7px; }
.decision-note.gpt { background:var(--purple-soft); border:1px solid #dbc7ef; }
.decision-guidance { color:#655176; font-size:10.5px; font-weight:750; margin-top:7px; }
.risk-evidence-table { border:1px solid #e1e4df; border-radius:8px; overflow:hidden; }
.risk-evidence-row { display:grid; grid-template-columns:minmax(0,1fr) 110px 76px; gap:9px; align-items:center; padding:8px 10px; border-bottom:1px solid #e5e7e3; font-size:10.5px; color:#3c4455; }
.risk-evidence-row:last-child { border-bottom:0; }
.risk-evidence-row.header { background:#f6f7f4; color:#687184; font:800 8.5px "IBM Plex Mono",Consolas,monospace; text-transform:uppercase; }
.severity-pill.high { background:#fde2df; color:#9a2d27; }
.severity-pill.medium { background:#fff0cf; color:#875500; }
.severity-pill.low { background:#d9eee4; color:#1f6b51; }
.approval-summary { display:flex; flex-wrap:wrap; gap:6px; margin-top:5px; }
.approval-summary-item { border:1px solid #dfe2dd; border-radius:7px; padding:6px 8px; background:#fafbf9; color:#596273; font-size:9.5px; }
.approval-summary-item.approved { border-color:#c2decf; background:var(--green-soft); color:var(--green); }
.approval-summary-item.final { border-color:#cdb8e4; background:var(--purple-soft); color:#65358f; }
.upside { grid-column:1/-1; background:var(--green-soft); border:1px solid #c2decf; color:#245e47; border-radius:8px; padding:11px 12px; font-size:11.5px; }
.upside-title { color:#174c38; font-size:13px; font-weight:900; margin-bottom:5px; }
.approval-queue { border-top:1px solid #dfe2dd; margin-top:18px; padding-top:14px; }
.approval-queue-intro { color:#687184; font-size:11px; margin:-3px 0 10px; }
.approval-queue-row { border:1px solid #dfe2dd; border-radius:8px; padding:9px 11px; background:#fbfcfa; margin-bottom:7px; }
.approval-queue-row.done { border-color:#c2decf; background:#f0f8f4; }
.approval-queue-row.rejected { border-color:#eab3ac; background:#fdf1ef; }
.approval-queue-title { color:var(--ink); font-size:11.5px; font-weight:850; }
.approval-queue-copy { color:#667085; font-size:10.5px; line-height:1.4; margin-top:3px; }
.final-banner { border-radius:10px; padding:18px 20px; margin:10px 0 16px; box-shadow:0 8px 22px rgba(18,23,43,.18); }
.final-banner-title { font-size:24px; line-height:1.2; font-weight:900; margin-bottom:6px; }
.final-banner-body { font-size:14px; line-height:1.45; max-width:920px; }
.final-banner-meta { margin-top:10px; font:11px "IBM Plex Mono",Consolas,monospace; opacity:.9; overflow-wrap:anywhere; }
.final-banner.active { background:#14532d; color:#fff; }
.final-banner.rejected { background:#991b1b; color:#fff; }
.final-banner.need-more { background:#92400e; color:#fff; }
.final-banner.renegotiate { background:#312e81; color:#fff; }
.snapshot-card.navy { background:#e9e8f8; border-color:#cbc7e9; }
.snapshot-card.navy .snapshot-value { color:#312e81; }
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
.stButton > button[kind="primary"] { min-height:48px; background:var(--ink)!important; color:#fff!important; border-color:var(--ink)!important; font-size:13px; }
.stButton > button[kind="primary"]:hover { background:#202842!important; color:#fff!important; }
.stButton > button:disabled { border-color:#dfe2dd!important; color:#596273!important; background:#f0f1ed!important; cursor:not-allowed; opacity:1; }
.stTabs [data-baseweb="tab-highlight"] { background-color:var(--purple); }
.stTabs [data-baseweb="tab"] { color:#4b5563; font-weight:750; }
.stTabs [aria-selected="true"] { color:var(--ink)!important; }
div[data-testid="stExpander"] { background:#fff; border-color:var(--line); border-radius:8px; }
.stMarkdown h5 { font-size:14px; margin:.15rem 0 .45rem; }
@media (max-width:1100px) { .snapshot-grid{grid-template-columns:repeat(2,minmax(0,1fr));} .console-header{position:relative;} .decision-body{grid-template-columns:1fr;} .upside{grid-column:auto;} .agent-kpi-label{min-height:0;} }
@media (max-width:760px) { .block-container{padding-left:.75rem;padding-right:.75rem;} .console-header{align-items:flex-start;flex-direction:column;} .header-badges{justify-content:flex-start;} .snapshot-grid{grid-template-columns:1fr;} .stepper{grid-template-columns:1fr;} .contract-heading{flex-direction:column;} .approval-progress-grid,.founder-insight-grid,.gate-kpi-grid{grid-template-columns:1fr;} .risk-evidence-row{grid-template-columns:1fr;} .risk-evidence-row.header{display:none;} .final-banner-title{font-size:20px;} }
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


def zone2_founder_insight_facts(
    backend: Any,
    team_pack: dict[str, Any],
) -> dict[str, Any]:
    """Build a sanitized fact payload; OpenAI never receives raw restricted IDs."""
    finance_handoff = backend.finance.d5_handoff
    risk_handoff = backend.risk.d5_handoff
    transaction_ids = list(
        risk_handoff.transaction_hold_txn_ids if risk_handoff else []
    )
    transaction_descriptions = [
        {
            "txn_id": str(row.get("txn_id")),
            "description": str(row.get("description", "")),
        }
        for row in team_pack.get("08_BANK_TXN", [])
        if str(row.get("txn_id")) in transaction_ids
    ]
    con004_margin = next(
        (
            object_dump(item)
            for item in backend.finance.margin_analysis
            if item.contract_id == "CON-004"
        ),
        {},
    )
    ord004 = next(
        (
            object_dump(item)
            for item in backend.risk.execution_risks
            if item.order_id == "ORD-004"
        ),
        {},
    )
    candidates = [
        {
            "credit_case_id": item.credit_case_id,
            "eligibility_score": item.eligibility_score,
            "priority_rank": item.priority_rank,
            "candidate_status": item.candidate_status,
            "evidence_missing": item.evidence_missing,
            "precheck_note": item.precheck_note,
        }
        for item in backend.finance.credit_candidates
    ]
    return {
        "transaction_ids": transaction_ids,
        "transaction_count": len(transaction_ids),
        "transaction_amount_vnd": (
            risk_handoff.transaction_hold_amount_vnd if risk_handoff else 0
        ),
        "transaction_context": transaction_descriptions,
        "financial_flow_paused": bool(
            risk_handoff.financial_flow_paused if risk_handoff else False
        ),
        "worst_month": finance_handoff.worst_month if finance_handoff else None,
        "worst_month_funding_need_vnd": (
            backend.finance.cashflow.worst_month_funding_need_vnd
        ),
        "con004_gross_margin": con004_margin.get("gross_margin"),
        "margin_target": con004_margin.get("target_margin", 0.28),
        "credit_candidates": candidates,
        "credit_priority_order": ["CR-004", "CR-001", "CR-002", "CR-003"],
        "ord004_contract_id": ord004.get("contract_id", "CON-003"),
        "ord004_penalty_vnd_per_day": ord004.get(
            "potential_penalty_vnd_per_day"
        ),
        "ord004_late_days_threshold": ord004.get(
            "late_delivery_days_threshold", 7
        ),
        "cr003_contract_id": "CON-005",
        "required_ids": [
            "TXN-006",
            "TXN-007",
            "CON-004",
            "CR-004",
            "CR-001",
            "CR-002",
            "CR-003",
            "ORD-004",
            "CON-003",
            "CON-005",
        ],
    }


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
    analysis_done = st.session_state.get("con004_analysis_status") == "analyzed"
    active = (
        "ANALYZE"
        if detail_contract_id != "CON-004" or not analysis_done
        else current_stage(final_state)
    )
    labels = ["ANALYZE", "BLOCKED_AP1", "PROPOSED", "DECISION_READY", "FINAL"]
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


def con004_analysis_done() -> bool:
    return st.session_state.get("con004_analysis_status") == "analyzed"


def render_founder_approval_progress() -> None:
    """Show AP-1..AP-5 progress directly below the CON-004 identity."""
    analysis_done = con004_analysis_done()
    ap1_done = st.session_state.ap1_status == "approved"
    ap2_done = st.session_state.ap2_status == "approved"
    ap3_done = st.session_state.ap3_status == "approved"
    ap4_done = st.session_state.ap4_status == "approved"
    ap5_done = st.session_state.final_state in FINAL_STATES
    statuses = [
        ("AP-1", ap1_done, analysis_done, "Tạm giữ giao dịch"),
        ("AP-2", ap2_done, ap1_done, "Vốn lưu động"),
        ("AP-3", ap3_done, ap1_done, "Bảo lãnh thực hiện"),
        ("AP-4", ap4_done, ap2_done and ap3_done, "Mở sandbox"),
        ("AP-5", ap5_done, ap4_done, "Quyết định cuối"),
    ]
    approved_count = sum(done for _, done, _, _ in statuses)
    progress = approved_count / len(statuses) * 100
    stages = []
    for approval_id, done, unlocked, description in statuses:
        status_value = (
            st.session_state.final_state
            if approval_id == "AP-5"
            else st.session_state.get(APPROVAL_ID_TO_STATUS_KEY[approval_id], "pending")
        )
        if status_value == "rejected":
            klass = "waiting"
            status_text = "Founder đã từ chối"
        elif done:
            klass = "complete"
            status_text = "✓ Founder đã duyệt"
        elif unlocked:
            klass = "waiting"
            status_text = "Đang chờ Founder"
        else:
            klass = ""
            status_text = "Chưa mở"
        stages.append(
            f'''<div class="approval-stage {klass}">
                <div class="approval-stage-id">{esc(approval_id)} · {esc(description)}</div>
                <div class="approval-stage-status">{esc(status_text)}</div>
            </div>'''
        )
    st.markdown(
        f'''<section class="approval-progress">
            <div class="approval-progress-head">
                <div class="approval-progress-title">Tiến độ Founder phê duyệt · AP-1 → AP-5</div>
                <div class="approval-progress-count">{approved_count}/{len(statuses)} HOÀN TẤT</div>
            </div>
            <div class="approval-progress-track"><div class="approval-progress-fill" style="width:{progress:.0f}%"></div></div>
            <div class="approval-progress-grid">{''.join(stages)}</div>
        </section>''',
        unsafe_allow_html=True,
    )


def render_analysis_launcher() -> None:
    """Expose one deliberate frontend transition before revealing cached analysis."""
    st.markdown('<div style="height:32px"></div>', unsafe_allow_html=True)
    _, action, _ = st.columns([0.18, 0.64, 0.18])
    with action:
        if action.button(
            "Phân tích chi tiết cho CON-004",
            type="primary",
            width="stretch",
            key="analyze_con004",
            help="Hiển thị kết quả phân tích đã được backend chuẩn bị cho CON-004.",
        ):
            with st.spinner("Đang tổng hợp kết quả từ Finance & Data và Risk & Compliance..."):
                time.sleep(0.65)
            st.session_state.con004_analysis_status = "analyzed"
            st.session_state.con004_analysis_completed_at = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            st.session_state.action_toast = (
                "Finance & Data Agent và Risk & Compliance Agent đã hoàn tất phân tích CON-004."
            )
            st.rerun()
    st.markdown('<div style="height:38px"></div>', unsafe_allow_html=True)


def render_runtime_evidence(card: dict[str, Any]) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    events = [(now, "INGESTION", "14 sheets validated")]
    if con004_analysis_done():
        events.extend(
            [
                (now, "FINANCE", "Cashflow and margin analyzed"),
                (now, "RISK", "RR-001 critical cluster detected"),
                (now, "GOVERNANCE", "AP-1 created"),
            ]
        )
    else:
        events.append((now, "ORCHESTRATOR", "CON-004 analysis waiting for Founder trigger"))
    if st.session_state.ap1_status == "approved":
        events.extend(
            [
                (now, "FOUNDER", "AP-1 approved"),
                (now, "MASKING", "restricted fields tokenized"),
            ]
        )
    for approval_id, status_key in APPROVAL_ID_TO_STATUS_KEY.items():
        if st.session_state.get(status_key) == "rejected":
            reason = st.session_state.get(f"{approval_id.lower().replace('-', '')}_reject_reason", "")
            request_id = f"{APPROVAL_ID_TO_REQUEST_ID[approval_id]}-REJECT"
            events.append(
                (
                    now,
                    "FOUNDER",
                    f"{approval_id} rejected · {request_id}"
                    + (f" · {reason}" if reason else ""),
                )
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


FINAL_STATES = {"ACTIVE", "REJECTED", "NEED_MORE_INFORMATION", "RENEGOTIATE"}


def _display_month(value: Any) -> str:
    text = str(value or "")
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year, month = text.split("-")
        return f"{month}/{year}"
    return text or "chưa xác định"


def approval_status_label(status: str, approval_id: str) -> str:
    return {
        "approved": f"Đã duyệt · {approval_id}",
        "rejected": f"Đã từ chối · {approval_id}",
        "need_more_information": f"Cần thêm thông tin · {approval_id}",
        "renegotiate": f"Đàm phán lại · {approval_id}",
    }.get(str(status), f"Chưa duyệt · {approval_id}")


def approval_status_class(status: str) -> str:
    if status == "approved":
        return "approved"
    if status in {"rejected", "need_more_information", "renegotiate"}:
        return "rejected"
    return "pending"


APPROVAL_REJECT_REASONS = {
    "AP-1": [
        "Chưa đủ căn cứ để giữ giao dịch",
        "Cần xác minh thêm trước khi quyết định",
        "Chấp nhận rủi ro, không cần giữ",
        "Khác",
    ],
    "AP-2": [
        "Điều kiện tín dụng (lãi suất/kỳ hạn/phí) chưa phù hợp",
        "Muốn cân nhắc phương án khác trước khi vay/bảo lãnh",
        "Chưa cần thiết ở giai đoạn này",
        "Khác",
    ],
    "AP-3": [
        "Điều kiện tín dụng (lãi suất/kỳ hạn/phí) chưa phù hợp",
        "Muốn cân nhắc phương án khác trước khi vay/bảo lãnh",
        "Chưa cần thiết ở giai đoạn này",
        "Khác",
    ],
    "AP-4": [
        "Chưa sẵn sàng chia sẻ dữ liệu ra đối tác ngoài",
        "Muốn rà lại dữ liệu đã masking trước khi gửi",
        "Muốn đổi kênh nộp (không qua API)",
        "Khác",
    ],
}

APPROVAL_REJECT_CONSEQUENCES = {
    "AP-1": "Cụm giao dịch nghi ngờ (178M) vẫn tiếp tục di chuyển. Toàn bộ gói tín dụng (AP-2 → AP-5) tạm khóa.",
    "AP-2": "Thiếu 950M vốn lưu động trong gói đề xuất. AP-4 và AP-5 tạm khóa.",
    "AP-3": "Thiếu 420M bảo lãnh thực hiện trong gói đề xuất. AP-4 và AP-5 tạm khóa.",
    "AP-4": "Không có hồ sơ nào được gửi ra bank API. AP-5 tạm khóa.",
}

APPROVAL_ID_TO_STATUS_KEY = {
    "AP-1": "ap1_status",
    "AP-2": "ap2_status",
    "AP-3": "ap3_status",
    "AP-4": "ap4_status",
}

APPROVAL_ID_TO_REQUEST_ID = {
    "AP-1": "APR-001",
    "AP-2": "APR-002",
    "AP-3": "APR-003",
    "AP-4": "APR-004",
}


def severity_class(severity: str) -> str:
    normalized = str(severity or "medium").strip().lower()
    return normalized if normalized in {"high", "medium", "low"} else "medium"


def final_state_copy(final_state: str) -> tuple[str, str, str] | None:
    return {
        "ACTIVE": (
            "active",
            "CON-004 đã được phê duyệt",
            "Founder đã chốt AP-5. Hồ sơ chuyển sang ACTIVE sau khi AP-1 đến AP-4 đã hoàn tất. Kiểm tra Runtime Log để đối chiếu mã phê duyệt của người ra quyết định.",
        ),
        "REJECTED": (
            "rejected",
            "CON-004 đã bị từ chối",
            "Founder chốt không tiếp tục cơ hội này. Hệ thống giữ lại bằng chứng và lịch sử phê duyệt để giải trình quyết định.",
        ),
        "NEED_MORE_INFORMATION": (
            "need-more",
            "Founder yêu cầu bổ sung thông tin",
            "Decision Card chưa đủ để chốt. Cần bổ sung bằng chứng còn thiếu, đặc biệt xác nhận nhà cung cấp liên quan CR-003/CON-005 trước khi xem xét tiếp.",
        ),
        "RENEGOTIATE": (
            "renegotiate",
            "Founder chọn đàm phán lại CON-004",
            "Cơ hội chưa bị từ chối, nhưng điều kiện hiện tại chưa đủ tốt. Cần đàm phán lại điều khoản, timeline, bảo lãnh hoặc vùng đệm dòng tiền trước khi chốt.",
        ),
    }.get(final_state)


def render_final_state_banner(final_state: str, human_approval_id: str | None) -> None:
    copy = final_state_copy(final_state)
    if copy is None:
        return
    klass, title, body = copy
    st.markdown(
        f'''<section class="final-banner {klass}" data-final-state="{esc(final_state)}">
            <div class="final-banner-title">{esc(title)}</div>
            <div class="final-banner-body">{esc(body)}</div>
            <div class="final-banner-meta">TRẠNG THÁI: {esc(final_state)} · HUMAN APPROVAL: {esc(human_approval_id or "chưa ghi nhận")}</div>
        </section>''',
        unsafe_allow_html=True,
    )


def render_cashflow_credit_insights(card: dict[str, Any], backend_output: Any) -> None:
    cashflow_months = list(backend_output.finance.cashflow.months)
    worst = (
        max(cashflow_months, key=lambda item: item.funding_need_vnd)
        if cashflow_months
        else None
    )
    upside = card.get("upside_if_conditions_met", {})
    breakdown = card.get("financial_ask", {}).get("breakdown", [])
    credit_by_id = {str(item.get("credit_id")): item for item in breakdown}
    cr001 = credit_by_id.get("CR-001", {})
    cr002 = credit_by_id.get("CR-002", {})
    missing = next(
        (
            item.get("description")
            for item in card.get("missing_evidence", [])
            if "CR-003" in str(item.get("description", ""))
            or "CR-003" in [str(value) for value in item.get("blocks", [])]
        ),
        "Thiếu xác nhận từ nhà cung cấp cho CR-003.",
    )
    worst_month = _display_month(getattr(worst, "month", None))
    recovery_month = _display_month(upside.get("recovery_month"))
    st.markdown("#### Dòng tiền & Gói tín dụng")
    st.markdown(
        f'''<div class="founder-insight-grid">
            <article class="founder-insight-card">
                <div class="founder-insight-label">Dòng tiền · Tình huống cần xử lý</div>
                <div class="founder-insight-main">Tháng {esc(worst_month)}, OPC sẽ thiếu tới {esc(money(getattr(worst, "funding_need_vnd", None)))} để duy trì hoạt động. Đây là tháng căng nhất trong 6 tháng tới.</div>
                <div class="founder-insight-next"><strong>Founder cần làm:</strong> hoàn tất nguồn vay trước thời điểm này. Nếu xử lý kịp, dòng tiền dự kiến phục hồi từ tháng {esc(recovery_month)}.</div>
            </article>
            <article class="founder-insight-card">
                <div class="founder-insight-label">Gói tín dụng · Phương án đề xuất</div>
                <div class="founder-insight-main">Gói vay chính gồm {len(breakdown)} khoản, tổng {esc(money(card.get("financial_ask", {}).get("total")))}: CR-001 ({esc(money(cr001.get("amount")))}) cho vốn lưu động và CR-002 ({esc(money(cr002.get("amount")))}) cho bảo lãnh thực hiện hợp đồng.</div>
                <div class="founder-insight-next"><strong>Chưa đưa vào gói:</strong> CR-003 đang tạm giữ. {esc(missing)} Cần bổ sung bằng chứng này trước khi xem xét lại.</div>
            </article>
        </div>''',
        unsafe_allow_html=True,
    )


def render_decision_partner_card(card: dict[str, Any], backend_output: Any) -> None:
    del backend_output  # Facts are already consolidated in the deterministic Decision Card.
    rejected_approval = next(
        (
            approval_id
            for approval_id, status_key in APPROVAL_ID_TO_STATUS_KEY.items()
            if st.session_state.get(status_key) == "rejected"
        ),
        None,
    )
    if rejected_approval:
        state = "ĐÃ DỪNG DO KHÔNG DUYỆT"
        body = APPROVAL_REJECT_CONSEQUENCES[rejected_approval]
        next_action = "Bước tiếp theo: Founder có thể bấm Xem lại lựa chọn ở Hàng chờ phê duyệt nếu muốn mở lại bước này."
    elif st.session_state.ap1_status != "approved":
        state = "ĐANG CHỜ AP-1"
        body = (
            "Decision & Partner đang chờ phản hồi từ Founder cho Điểm duyệt AP-1. "
            "Agent chưa mở đề xuất tín dụng cho đến khi cụm giao dịch rủi ro được xác nhận tạm giữ."
        )
        next_action = "Bước tiếp theo: Founder duyệt AP-1 tại Hàng chờ phê duyệt phía cuối màn hình."
    elif st.session_state.ap4_status == "approved":
        state = "SẴN SÀNG AP-5"
        body = (
            "Hồ sơ đã qua AP-1 đến AP-4. Bank API sandbox chỉ thực hiện pre-check, "
            "không gửi hồ sơ tới ngân hàng thật."
        )
        next_action = "Bước tiếp theo: đọc Decision Card, đối chiếu bằng chứng và chốt AP-5."
    else:
        state = "ĐANG CHUẨN BỊ GÓI"
        body = (
            "Decision & Partner đã nhận kết quả từ Finance & Data và Risk & Compliance. "
            "Agent đang chuẩn bị gói CR-001 + CR-002, đồng thời giữ CR-003 ở trạng thái chờ bổ sung bằng chứng."
        )
        next_action = "Bước tiếp theo: xử lý AP-2 và AP-3; AP-4 sẽ mở khi cả hai hoàn tất."
    st.markdown(
        f'''<section class="partner-card">
            <div class="partner-card-head">
                <div class="partner-card-title">Decision & Partner Agent · Bằng chứng bổ sung</div>
                <span class="partner-card-state">{esc(state)}</span>
            </div>
            <div class="partner-card-body">{esc(body)}</div>
            <div class="partner-card-next">{esc(next_action)}</div>
        </section>''',
        unsafe_allow_html=True,
    )


def render_decision_partner_technical(card: dict[str, Any]) -> None:
    if st.session_state.ap1_status != "approved":
        return
    with st.expander("Bằng chứng kỹ thuật · Decision & Partner", expanded=False):
        cases = related_credit_cases("CON-004")
        if not cases.empty:
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
        fit_df = pd.DataFrame(card.get("bank_fit_matrix", []))
        if not fit_df.empty:
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
        st.json(card.get("llm_meta", {}), expanded=False)


def render_cashflow_credit_data(contract_id: str, card: dict[str, Any]) -> None:
    cash_tab, credit_tab = st.tabs(["Dòng tiền", "Gói tín dụng"])
    with cash_tab:
        cash_rows = filtered_cashflow_rows()
        cash = pd.DataFrame([item.model_dump() for item in cash_rows])
        if not cash.empty:
            st.line_chart(
                cash.set_index("month")[["funding_need_vnd", "reserve_gap_vnd"]]
            )
            if contract_id != "CON-004":
                worst_cash = max(cash_rows, key=lambda item: item.funding_need_vnd)
                recovery_month = card.get("upside_if_conditions_met", {}).get(
                    "recovery_month", "chưa xác định"
                )
                info_card(
                    "Bước xử lý dòng tiền",
                    f"Nhu cầu vốn đạt đỉnh {money(worst_cash.funding_need_vnd)} vào {_display_month(worst_cash.month)}. "
                    f"Founder nên chốt nguồn vốn trước tháng này; mô hình kỳ vọng phục hồi ở {_display_month(recovery_month)}.",
                )
        else:
            st.info("Không có dữ liệu dòng tiền trong phạm vi kỳ đã chọn.")
    with credit_tab:
        cases = related_credit_cases(contract_id)
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
        if contract_id == "CON-004":
            credit_metrics = st.columns(2)
            credit_metrics[0].metric(
                "Nhu cầu vốn",
                money(card["financial_ask"]["total"]),
            )
            credit_metrics[1].metric(
                "Tài sản đảm bảo",
                money(card["financial_ask"]["collateral_total"]),
            )


def render_gate_reason_kpis(card: dict[str, Any]) -> None:
    findings = list(getattr(backend.risk, "transaction_findings", []))
    risk_scores = [float(getattr(item, "risk_score", 0) or 0) for item in findings]
    risk_score_text = " · ".join(f"{score:g}" for score in risk_scores) if risk_scores else "n/a"
    risk_threshold = getattr(
        getattr(backend.risk, "rule_snapshot", None),
        "transaction_risk_threshold",
        85,
    )
    governance_threshold = getattr(
        getattr(backend.risk, "rule_snapshot", None),
        "governance_amount_threshold_vnd",
        300_000_000,
    )
    amount_by_credit = {
        str(item.get("credit_id")): item.get("amount")
        for item in card.get("financial_ask", {}).get("breakdown", [])
    }
    governance_parts = [
        f"{credit_id} {money(amount_by_credit[credit_id])}"
        for credit_id in ("CR-001", "CR-002")
        if credit_id in amount_by_credit
    ]
    api002 = next(
        (
            row
            for row in team_pack.get("12_API_CATALOG", [])
            if str(row.get("api_id")) == "API-002"
        ),
        {},
    )
    api_provider = api002.get("bank_name") or api002.get("provider") or api002.get("partner_name") or "VietinBank"
    st.markdown(
        f'''<div class="gate-kpi-grid">
            <div class="gate-kpi-card danger">
                <div class="gate-kpi-label">Điểm rủi ro giao dịch</div>
                <div class="gate-kpi-value">{esc(risk_score_text)} / 100</div>
                <div class="gate-kpi-note">Ngưỡng kích hoạt AP-1: ≥{esc(risk_threshold)} · RR-001</div>
            </div>
            <div class="gate-kpi-card danger">
                <div class="gate-kpi-label">Ngưỡng phê duyệt tài chính</div>
                <div class="gate-kpi-value">{esc(' & '.join(governance_parts) or 'n/a')} &gt; {esc(money(governance_threshold))}</div>
                <div class="gate-kpi-note">Cần Founder duyệt · RR-005 · AP-2, AP-3</div>
            </div>
            <div class="gate-kpi-card">
                <div class="gate-kpi-label">Gửi hồ sơ ra ngoài</div>
                <div class="gate-kpi-value">API-002 · {esc(api_provider)}</div>
                <div class="gate-kpi-note">Luôn cần Founder duyệt trước khi gửi · RR-004 · AP-4</div>
            </div>
        </div>''',
        unsafe_allow_html=True,
    )


def render_bank_api_sandbox(*, include_failure_tester: bool = False) -> None:
    if st.session_state.ap4_status != "approved":
        st.markdown(
            '''<section class="sandbox-box locked">
                <div class="sandbox-title">Bank API sandbox · đang khóa</div>
                <div class="sandbox-copy">Sandbox chỉ mở sau AP-4. Trước thời điểm đó, không hồ sơ nào được gửi ra ngoài, kể cả môi trường mock/sandbox.</div>
            </section>''',
            unsafe_allow_html=True,
        )
        return

    st.markdown("#### Bank API sandbox")
    candidate_by_id = {item.credit_case_id: item for item in backend.finance.credit_candidates}
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
    scenario_status = int(st.session_state.get("bank_api_scenario_status", 200))
    if include_failure_tester:
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
            st.warning(f"Safe failure: {api_result.get('required_handling')}")
        with st.expander("Chi tiết phản hồi kỹ thuật", expanded=False):
            st.json(api_result, expanded=False)


def render_bank_api_failure_tester() -> None:
    if st.session_state.ap4_status != "approved":
        st.caption("Bank API safe-failure tester sẽ mở sau AP-4.")
        return
    scenario_map = {
        "Thành công": 200,
        "Dữ liệu đầu vào không hợp lệ": 400,
        "Xác thực sandbox thất bại": 401,
        "Hồ sơ trùng hoặc xung đột": 409,
        "Vượt giới hạn gọi thử": 429,
        "Dịch vụ sandbox tạm thời gián đoạn": 503,
    }
    current_status = int(st.session_state.get("bank_api_scenario_status", 200))
    current_label = next(
        (label for label, status in scenario_map.items() if status == current_status),
        "Thành công",
    )
    with st.expander("Chế độ kiểm thử lỗi kỹ thuật", expanded=False):
        scenario_label = st.selectbox(
            "Kịch bản phản hồi",
            list(scenario_map),
            index=list(scenario_map).index(current_label),
            key="bank_api_test_scenario",
        )
        st.session_state.bank_api_scenario_status = scenario_map[scenario_label]
        st.caption(
            "Khu vực này phục vụ giám khảo/tester kiểm tra safe failure. Zone 2 sẽ dùng kịch bản này cho lần gọi Bank API mock tiếp theo."
        )


def render_runtime_export(card: dict[str, Any]) -> None:
    if st.button(
        "Xuất runtime log mẫu",
        width="stretch",
        key="export_runtime_log",
    ):
        log_path = write_json(
            ROOT / "runtime_logs" / "sample_runtime_log.json",
            build_sample_runtime_log(card),
        )
        card_path = write_json(
            ROOT / "output" / "demo_decision_card.json",
            card,
        )
        st.success(f"Đã xuất {log_path.name} và {card_path.name}")


def render_decision_card(card: dict[str, Any]) -> None:
    approvals = {
        str(item.get("id")): str(item.get("status", "pending"))
        for item in card.get("approval_required", [])
    }
    credit_context = {
        "CR-001": "Vốn lưu động để bù thiếu hụt tiền mặt trong giai đoạn căng nhất.",
        "CR-002": "Bảo lãnh thực hiện để triển khai CON-004 đúng cam kết.",
    }
    cr_to_ap = {"CR-001": "AP-2", "CR-002": "AP-3"}
    financial_rows = []
    for item in card.get("financial_ask", {}).get("breakdown", []):
        credit_id = str(item.get("credit_id"))
        ap_id = cr_to_ap.get(credit_id, "AP")
        status = approvals.get(ap_id, "pending")
        financial_rows.append(
            f'''<div class="decision-row">
                <div><div class="financial-main">{esc(credit_id)} → {esc(item.get("bank_product") or "đang ghép")}<span class="approval-pill {approval_status_class(status)}">{esc(approval_status_label(status, ap_id))}</span></div>
                <div class="financial-sub">{esc(credit_context.get(credit_id, "Khoản tín dụng trong gói đề xuất."))}</div></div>
                <strong>{esc(money(item.get("amount")))}</strong>
            </div>'''
        )

    risk_evidence_rows = []
    for item in card.get("risks_remaining", []):
        severity = str(item.get("severity") or "Medium")
        risk_evidence_rows.append(
            f'''<div class="risk-evidence-row"><span>{esc(item.get("description"))}</span><span>{esc(item.get("rule_ref") or "Risk rule")}</span><span class="severity-pill {severity_class(severity)}">{esc(severity)}</span></div>'''
        )
    for item in card.get("missing_evidence", []):
        evidence_ref = ", ".join(str(value) for value in item.get("blocks", [])) or "Evidence"
        risk_evidence_rows.append(
            f'''<div class="risk-evidence-row"><span>{esc(item.get("description"))}</span><span>{esc(evidence_ref)}</span><span class="severity-pill high">High</span></div>'''
        )
    risk_evidence_table = (
        '''<div class="risk-evidence-table"><div class="risk-evidence-row header"><span>Nội dung</span><span>Rule / evidence</span><span>Mức độ</span></div>'''
        + "".join(risk_evidence_rows)
        + "</div>"
        if risk_evidence_rows
        else '<div class="decision-note">Không còn rủi ro hoặc bằng chứng bắt buộc cần xử lý.</div>'
    )

    conflict_rows = "".join(
        f'''<div class="decision-note gpt"><strong>{esc(item.get("description"))}</strong><br><span style="color:#6d5a7f">Cách xử lý: {esc(item.get("resolution_note"))}</span></div>'''
        for item in card.get("conflicts_detected", [])
    ) or '<div class="decision-note gpt">Không có mâu thuẫn nghiêm trọng sau khi AP-1 được xử lý.</div>'
    llm_meta = card.get("llm_meta", {}) or {}
    llm_model = str(llm_meta.get("model") or openai_model or "gpt-4o").upper()
    llm_mode = str(llm_meta.get("mode") or "fallback").upper()
    gpt_source_tag = f"{llm_model} · {'LIVE' if llm_mode == 'LIVE' else 'FALLBACK'}"

    approval_summary = []
    for item in card.get("approval_required", []):
        approval_id = str(item.get("id"))
        status = str(item.get("status", "pending"))
        klass = "approved" if status == "approved" else "final" if approval_id == "AP-5" and status != "pending" else ""
        symbol = "Đã duyệt" if status == "approved" else {
            "rejected": "Đã từ chối",
            "need_more_information": "Cần thông tin",
            "renegotiate": "Đàm phán lại",
        }.get(status, "Chưa duyệt")
        approval_summary.append(
            f'<span class="approval-summary-item {klass}">{esc(approval_id)} · {esc(symbol)}</span>'
        )

    upside = card.get("upside_if_conditions_met", {})
    st.markdown(
        f'''<section class="decision-card">
            <div class="decision-head">
                <div><div class="decision-kicker">Decision Card · {esc(card.get("decision_version"))}</div><div class="decision-state">Trạng thái hồ sơ: {esc(card.get("state"))}</div></div>
                <div class="decision-rec">{esc(card.get("recommendation"))}</div>
            </div>
            <div class="decision-body">
                <div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-det">DỮ LIỆU ĐÃ KIỂM CHỨNG</span>Nhu cầu tài chính</div>{''.join(financial_rows)}<div class="decision-row"><span>Tổng nhu cầu vốn</span><span class="decision-total">{esc(money(card.get("financial_ask", {}).get("total")))}</span></div></div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-det">DỮ LIỆU ĐÃ KIỂM CHỨNG</span>Rủi ro và bằng chứng cần xử lý</div>{risk_evidence_table}</div>
                </div>
                <div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-gpt">{esc(gpt_source_tag)}</span>Mâu thuẫn cần lưu ý</div>{conflict_rows}<div class="decision-guidance">↓ Xem Lý do đề xuất để hiểu vì sao hệ thống vẫn đưa ra khuyến nghị có điều kiện.</div></div>
                    <div class="decision-section"><div class="decision-section-title"><span class="source-tag tag-gpt">{esc(gpt_source_tag)}</span>Lý do đề xuất</div><div class="decision-note gpt">{esc(card.get("rationale"))}</div></div>
                </div>
                <div class="upside"><div class="upside-title">Nếu Founder duyệt đủ các bước trên, OPC nhận lại gì?</div>CON-004 có thể mang lại {esc(money(upside.get("gross_profit_vnd")))} lợi nhuận gộp và giúp dòng tiền phục hồi từ tháng {esc(_display_month(upside.get("recovery_month")))} với số dư cuối kỳ dự kiến {esc(money(upside.get("recovery_closing_cash_vnd")))}. Điều kiện là AP-1 đến AP-4 phải được xử lý đúng thứ tự trước khi Founder chốt AP-5.</div>
                <div class="decision-section" style="grid-column:1/-1;margin-bottom:0"><div class="decision-section-title">Trạng thái phê duyệt</div><div class="approval-summary">{''.join(approval_summary)}</div><div class="decision-guidance">Đọc xong phần trên, kéo xuống Hàng chờ phê duyệt để xử lý bước tiếp theo.</div></div>
            </div>
        </section>''',
        unsafe_allow_html=True,
    )


def founder_next_step() -> str:
    if detail_contract_id != "CON-004":
        return "Đọc Finance/Risk evidence của hợp đồng này; Decision Card sâu hiện chỉ áp dụng cho CON-004."
    rejected_approval = next(
        (
            approval_id
            for approval_id, status_key in APPROVAL_ID_TO_STATUS_KEY.items()
            if st.session_state.get(status_key) == "rejected"
        ),
        None,
    )
    if rejected_approval:
        return f"{rejected_approval} đã bị Founder từ chối. Luồng đang khóa; bấm Xem lại lựa chọn nếu muốn đưa bước này về pending."
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
for key in ("ap1_reject_reason", "ap2_reject_reason", "ap3_reject_reason", "ap4_reject_reason"):
    if key not in st.session_state:
        st.session_state[key] = ""
if "rejecting_approval_id" not in st.session_state:
    st.session_state.rejecting_approval_id = None
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
if "bank_api_scenario_status" not in st.session_state:
    st.session_state.bank_api_scenario_status = 200
if "openai_narrative_cache" not in st.session_state:
    st.session_state.openai_narrative_cache = None
if "zone2_founder_insight_cache" not in st.session_state:
    st.session_state.zone2_founder_insight_cache = None
if "con004_analysis_status" not in st.session_state:
    st.session_state.con004_analysis_status = "pending"
if "con004_analysis_completed_at" not in st.session_state:
    st.session_state.con004_analysis_completed_at = None
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

founder_insight_facts = zone2_founder_insight_facts(backend, team_pack)
founder_insight_key = founder_insight_signature(
    founder_insight_facts,
    openai_model,
)
founder_insights = build_founder_insights(
    founder_insight_facts,
    use_openai=False,
)
founder_insight_cache = st.session_state.zone2_founder_insight_cache
founder_insight_cache_is_current = (
    isinstance(founder_insight_cache, dict)
    and founder_insight_cache.get("signature") == founder_insight_key
)
founder_insight_scope_active = (
    page == "Chi tiết hợp đồng"
    and detail_contract_id == "CON-004"
    and con004_analysis_done()
)
if (
    founder_insight_scope_active
    and openai_enabled
    and not founder_insight_cache_is_current
):
    with st.spinner("OpenAI đang chuyển kết quả phân tích thành insight cho Founder..."):
        live_founder_insights = build_founder_insights(
            founder_insight_facts,
            use_openai=True,
        )
    founder_insight_cache = {
        "signature": founder_insight_key,
        **live_founder_insights,
    }
    st.session_state.zone2_founder_insight_cache = founder_insight_cache
    founder_insight_cache_is_current = True

if founder_insight_scope_active and founder_insight_cache_is_current:
    founder_insights = {
        key: value
        for key, value in founder_insight_cache.items()
        if key != "signature"
    }

llm_mode = decision_card.get("llm_meta", {}).get("mode", "fallback")
if not con004_analysis_done():
    openai_label = "CHỜ PHÂN TÍCH"
    openai_class = "warn"
elif st.session_state.ap1_status != "approved":
    founder_mode = founder_insights.get("llm_meta", {}).get("mode", "fallback")
    if founder_insight_scope_active and founder_mode == "live":
        openai_label = "LIVE · INSIGHT"
        openai_class = "good"
    elif founder_insight_scope_active:
        openai_label = "DỰ PHÒNG · INSIGHT"
        openai_class = "warn"
    else:
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


def credit_case_score(credit_case_id: str, cases: pd.DataFrame | None = None) -> float | None:
    source = cases if cases is not None and not cases.empty else credit_df
    if source.empty or "credit_case_id" not in source.columns or "eligibility_score" not in source.columns:
        return None
    rows = source[source["credit_case_id"].astype(str).eq(credit_case_id)]
    if rows.empty:
        rows = credit_df[credit_df["credit_case_id"].astype(str).eq(credit_case_id)]
    if rows.empty:
        return None
    value = rows.iloc[0].get("eligibility_score")
    return float(value) if pd.notna(value) else None


def credit_case_score_text(credit_case_id: str, cases: pd.DataFrame | None = None) -> str:
    score = credit_case_score(credit_case_id, cases)
    return f"{score:.2f}" if score is not None else "n/a"


def credit_priority_item(credit_case_id: str, label: str) -> str:
    return f"{credit_case_id} ({credit_case_score_text(credit_case_id)}) · {label}"


def overview_credit_takeaway(
    contract_scope: str,
    cases: pd.DataFrame,
) -> tuple[str, str]:
    """Return one concise, deterministic takeaway for the Overview credit tab."""
    if cases.empty:
        return (
            f"TAKEAWAY · {contract_scope}",
            "Chưa có hồ sơ tín dụng phù hợp trong workbook cho phạm vi đang chọn.",
        )
    if contract_scope == "CON-004":
        return (
            "TAKEAWAY · CON-004",
            f"CR-004 có điểm sẵn sàng cao nhất ({credit_case_score_text('CR-004', cases)}), phù hợp để ưu tiên xử lý trước. "
            "CR-001 và CR-002 là gói vốn chính tổng 1,37 tỷ VND nhưng vẫn cần Founder phê duyệt "
            "và hoàn tất bằng chứng liên quan.",
        )
    if contract_scope == "CON-005":
        return (
            "TAKEAWAY · CON-005",
            f"CR-003 là hồ sơ chuyên biệt cho CON-005 nhưng mới đạt {credit_case_score_text('CR-003', cases)} và đang thiếu xác nhận "
            "từ nhà cung cấp; chưa đủ cơ sở để đưa vào gói đề xuất.",
        )
    if contract_scope == "Tất cả hợp đồng":
        return (
            "TAKEAWAY · TOÀN BỘ PORTFOLIO",
            f"Có 4 hồ sơ tín dụng. CR-004 có điểm sẵn sàng cao nhất ({credit_case_score_text('CR-004', cases)}); "
            f"CR-003 thấp nhất ({credit_case_score_text('CR-003', cases)}) và đang bị giữ do thiếu xác nhận từ nhà cung cấp.",
        )
    return (
        f"TAKEAWAY · {contract_scope}",
        "Workbook chưa có credit case chuyên biệt cho hợp đồng này; bảng bên dưới hiển thị "
        "hồ sơ gần nhất để Founder đối chiếu, không phải đề xuất phê duyệt tự động.",
    )


def contract_status(contract_id: str) -> tuple[str, str]:
    margin = margin_for_contract(contract_id)
    risks = execution_risks_for_contract(contract_id)
    gross_margin = margin.get("gross_margin")
    if (
        contract_id == "CON-004"
        and backend.risk.financial_flow_paused
        and st.session_state.ap1_status != "approved"
    ):
        return "CRITICAL", "Bị chặn bởi RR-001/AP-1"
    if risks:
        return "HIGH", "Có rủi ro triển khai cần theo dõi"
    threshold = margin.get(
        "target_margin",
        getattr(getattr(backend.risk, "rule_snapshot", None), "margin_threshold", 0.28),
    )
    if gross_margin is not None and pd.notna(gross_margin) and float(gross_margin) < float(threshold):
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


def snapshot_cards_for_view(
    contract_id: str,
    *,
    overview_copy: bool = False,
) -> list[dict[str, str]]:
    audit = backend.finance.source_audit
    decision_short_name = "Decision" if overview_copy else "D&P"
    sheet_scope = {
        "Tất cả agent": (len(audit.loaded_sheets), f"Finance 8 · Risk 12 · {decision_short_name} 1"),
        "Finance & Data": (8, "Finance & Data sử dụng"),
        "Risk & Compliance": (12, "Risk & Compliance sử dụng"),
        "Decision & Partner": (1, "Decision & Partner sử dụng trực tiếp"),
    }
    sheet_count, sheet_sub = sheet_scope[agent_focus]
    total_records = sum(audit.row_counts.values())
    cards = [
        {"label": "Tổng số sheet đã đọc", "value": str(sheet_count), "sub": sheet_sub, "class": "health"},
        {"label": "Bản ghi đã kiểm tra", "value": str(total_records), "sub": "Dữ liệu đang đọc trực tiếp từ workbook" if overview_copy else "live workbook", "class": "health"},
        {"label": "Lỗi cấu trúc dữ liệu" if overview_copy else "Lỗi schema", "value": "0" if audit.core_complete else str(len(audit.missing_sheets)), "sub": "Không phát hiện lỗi" if overview_copy and audit.core_complete else "schema errors", "class": "health"},
        {"label": "Mã đối soát nguồn" if overview_copy else "Input hash", "value": workbook_hash if overview_copy else f"{workbook_hash[:4]}…", "sub": "10 ký tự đầu của mã SHA-256" if overview_copy else "đối soát nguồn", "class": "health"},
    ]
    if contract_id == "CON-004" and not overview_copy:
        visible_state = (
            "CHỜ PHÂN TÍCH"
            if not con004_analysis_done()
            else str(st.session_state.final_state)
        )
        state_style = {
            "ACTIVE": "health",
            "REJECTED": "danger",
            "NEED_MORE_INFORMATION": "warn",
            "RENEGOTIATE": "navy",
            "BLOCKED_BY_AP1": "danger",
            "CREDIT_PACKAGE_PROPOSED": "warn",
            "DECISION_READY": "health",
            "CHỜ PHÂN TÍCH": "warn",
        }.get(visible_state, "")
        state_sub = {
            "ACTIVE": "Founder đã phê duyệt AP-5",
            "REJECTED": "Founder không tiếp tục cơ hội",
            "NEED_MORE_INFORMATION": "Đang chờ bổ sung bằng chứng",
            "RENEGOTIATE": "Đang chờ điều khoản mới",
            "BLOCKED_BY_AP1": "Cần xử lý AP-1",
            "CREDIT_PACKAGE_PROPOSED": "Đang hoàn thiện AP-2 đến AP-4",
            "DECISION_READY": "Sẵn sàng để Founder chốt AP-5",
            "CHỜ PHÂN TÍCH": "Bấm Phân tích tại Zone 2",
        }.get(visible_state, "Trạng thái hiện tại của hợp đồng")
        cards[3] = {
            "label": "Trạng thái CON-004",
            "value": visible_state,
            "sub": state_sub,
            "class": state_style,
        }
    if contract_id == "CON-004" and not con004_analysis_done() and not overview_copy:
        cards.extend(
            [
                {"label": "Finance & Data Agent", "value": "CHỜ PHÂN TÍCH", "sub": "chưa tạo finance evidence", "class": ""},
                {"label": "Risk & Compliance Agent", "value": "CHỜ PHÂN TÍCH", "sub": "chưa tạo risk evidence", "class": ""},
                {"label": "Founder approval", "value": "0/3", "sub": "AP-1 đến AP-3 chưa mở", "class": ""},
                {"label": "Decision state", "value": "CHƯA SẴN SÀNG", "sub": "bấm Phân tích tại Zone 2", "class": "warn"},
            ]
        )
        return cards
    period_rows = filtered_cashflow_rows()
    breach_count = sum(bool(item.breach) for item in period_rows)
    worst = max(period_rows, key=lambda item: item.funding_need_vnd) if period_rows else None
    margin = margin_for_contract(contract_id)
    gross_margin = margin.get("gross_margin")
    target_margin = margin.get("target_margin", 0.28)
    gross_margin_text = (
        f"{float(gross_margin) * 100:.1f}%"
        if gross_margin is not None and pd.notna(gross_margin)
        else "n/a"
    )
    margin_standard_text = f"Ngưỡng tiêu chuẩn: {float(target_margin) * 100:.0f}%"
    margin_result_text = (
        "Đạt chuẩn"
        if gross_margin is not None
        and pd.notna(gross_margin)
        and float(gross_margin) >= float(target_margin)
        else "Không đạt chuẩn"
    )
    def month_label(value: str | None) -> str:
        if value and re.fullmatch(r"\d{4}-\d{2}", str(value)):
            year, month = str(value).split("-")
            return f"{month}/{year}"
        return str(value or "không có dữ liệu")
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
                {"label": "Tháng thiếu dự phòng tiền mặt" if overview_copy else "Cash reserve breach", "value": f"{breach_count}/{len(period_rows)} tháng", "sub": "Số tháng tiền mặt thấp hơn mức dự phòng tối thiểu" if overview_copy else selected_period, "class": "warn"},
                {"label": "Thiếu hụt vốn lớn nhất" if overview_copy else "Funding gap lớn nhất", "value": money(worst.funding_need_vnd if worst else None), "sub": f"Tháng căng nhất: {month_label(worst.month if worst else None)}" if overview_copy else worst.month if worst else "không có dữ liệu", "class": "warn"},
                {"label": f"Giá trị hợp đồng {contract_id}" if overview_copy else f"Giá trị {contract_id}", "value": money(contract_value), "sub": "Phạm vi hợp đồng đang chọn" if overview_copy else "contract scope", "class": ""},
                {"label": f"Biên lợi nhuận {contract_id}" if overview_copy else f"Gross margin {contract_id}", "value": gross_margin_text, "sub": f"{margin_standard_text} · {margin_result_text}" if overview_copy else f"ngưỡng {float(target_margin) * 100:.1f}%", "class": "danger" if gross_margin is not None and pd.notna(gross_margin) and float(gross_margin) < float(target_margin) else ""},
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
                {"label": "Tháng thiếu dự phòng tiền mặt" if overview_copy else "Portfolio cash reserve breach", "value": f"{breach_count}/{len(period_rows)} tháng", "sub": "Số tháng tiền mặt thấp hơn mức dự phòng tối thiểu" if overview_copy else selected_period, "class": "warn"},
                {"label": "Thiếu hụt vốn lớn nhất" if overview_copy else "Portfolio funding gap lớn nhất", "value": money(worst.funding_need_vnd if worst else None), "sub": f"Tháng căng nhất: {month_label(worst.month if worst else None)}" if overview_copy else worst.month if worst else "không có dữ liệu", "class": "warn"},
                {"label": f"Biên lợi nhuận {contract_id}" if overview_copy else f"Gross margin {contract_id}", "value": gross_margin_text, "sub": f"{money(contract_value)} · {margin_standard_text} · {margin_result_text}" if overview_copy else f"{money(contract_value)} · ngưỡng {float(target_margin) * 100:.1f}%", "class": "danger" if gross_margin is not None and pd.notna(gross_margin) and float(gross_margin) < float(target_margin) else ""},
                {"label": "Mức ưu tiên xử lý" if overview_copy else "Mức ưu tiên", "value": status, "sub": reason, "class": "danger" if status == "CRITICAL" else "warn" if status in {"HIGH", "WATCH"} else ""},
            ]
        )
    else:
        cards.extend(
            [
                {"label": "Tháng thiếu dự phòng tiền mặt" if overview_copy else "Cash reserve breach", "value": f"{breach_count}/{len(period_rows)} tháng", "sub": "Số tháng tiền mặt thấp hơn mức dự phòng tối thiểu" if overview_copy else selected_period, "class": "warn"},
                {"label": "Thiếu hụt vốn lớn nhất" if overview_copy else "Funding gap lớn nhất", "value": money(worst.funding_need_vnd if worst else None), "sub": f"Tháng căng nhất: {month_label(worst.month if worst else None)}" if overview_copy else worst.month if worst else "không có dữ liệu", "class": "warn"},
                {"label": "TXN cluster flagged", "value": money(risk.transaction_hold_amount_vnd), "sub": "portfolio", "class": "danger"},
                {"label": "Credit case đang mở", "value": str(len(credit_df)), "sub": "portfolio", "class": ""},
            ]
        )
    return cards


def render_stage_approval_controls() -> None:
    def _reject_reason_key(approval_id: str) -> str:
        return f"{approval_id.lower().replace('-', '')}_reject_reason"

    def _set_approval_status(approval_id: str, status: str, reason: str = "") -> None:
        status_key = APPROVAL_ID_TO_STATUS_KEY[approval_id]
        request_id = APPROVAL_ID_TO_REQUEST_ID[approval_id]
        st.session_state[status_key] = status
        st.session_state.human_approval_id = (
            f"{request_id}-REJECT" if status == "rejected" else request_id
        )
        st.session_state[_reject_reason_key(approval_id)] = reason if status == "rejected" else ""
        st.session_state.rejecting_approval_id = None
        st.session_state.action_warning = None
        if status == "approved":
            if approval_id == "AP-1":
                st.session_state.final_state = "CREDIT_PACKAGE_PROPOSED"
                st.session_state.action_toast = "Đã duyệt AP-1 và mở khóa luồng quyết định."
            elif approval_id == "AP-2":
                st.session_state.action_toast = "Đã duyệt AP-2 vốn lưu động."
            elif approval_id == "AP-3":
                st.session_state.action_toast = "Đã duyệt AP-3 bảo lãnh thực hiện."
            elif approval_id == "AP-4":
                st.session_state.final_state = "DECISION_READY"
                st.session_state.action_toast = "Đã duyệt AP-4. Bank API sandbox đã được mở."
        else:
            if approval_id == "AP-1":
                st.session_state.final_state = "BLOCKED_BY_AP1"
            elif st.session_state.final_state not in FINAL_STATES:
                st.session_state.final_state = "CREDIT_PACKAGE_PROPOSED"
            st.session_state.action_toast = f"Đã ghi nhận không duyệt {approval_id}."

    def _clear_approval_and_dependents(approval_id: str) -> None:
        cascade = {
            "AP-1": ["AP-1", "AP-2", "AP-3", "AP-4"],
            "AP-2": ["AP-2", "AP-4"],
            "AP-3": ["AP-3", "AP-4"],
            "AP-4": ["AP-4"],
        }[approval_id]
        for item_id in cascade:
            st.session_state[APPROVAL_ID_TO_STATUS_KEY[item_id]] = "pending"
            st.session_state[_reject_reason_key(item_id)] = ""
        if approval_id == "AP-1":
            st.session_state.final_state = "BLOCKED_BY_AP1"
        elif st.session_state.final_state not in FINAL_STATES:
            st.session_state.final_state = "CREDIT_PACKAGE_PROPOSED"
        st.session_state.bank_api_response = None
        st.session_state.rejecting_approval_id = None
        st.session_state.human_approval_id = None
        st.session_state.action_warning = None
        st.session_state.action_toast = f"Đã đưa {approval_id} về trạng thái chờ Founder xem lại."

    def _render_reject_confirmation(approval_id: str) -> None:
        reason_options = APPROVAL_REJECT_REASONS[approval_id]
        selected_reason = st.selectbox(
            "Lý do không duyệt",
            reason_options,
            key=f"{approval_id.lower().replace('-', '_')}_reject_reason_select",
        )
        custom_reason = ""
        if selected_reason == "Khác":
            custom_reason = st.text_input(
                "Lý do khác",
                key=f"{approval_id.lower().replace('-', '_')}_reject_reason_other",
                placeholder="Nhập lý do ngắn gọn",
            )
        final_reason = custom_reason.strip() if selected_reason == "Khác" and custom_reason.strip() else selected_reason
        confirm, cancel = st.columns(2)
        if confirm.button(
            "Xác nhận không duyệt",
            width="stretch",
            key=f"confirm_reject_{approval_id.lower().replace('-', '')}",
        ):
            _set_approval_status(approval_id, "rejected", final_reason)
            st.rerun()
        if cancel.button(
            "Hủy",
            width="stretch",
            key=f"cancel_reject_{approval_id.lower().replace('-', '')}",
        ):
            st.session_state.rejecting_approval_id = None
            st.rerun()

    def _render_approval_row(
        approval_id: str,
        title: str,
        subtitle: str,
        blocked_item: bool,
        approve_key: str,
    ) -> None:
        status_key = APPROVAL_ID_TO_STATUS_KEY[approval_id]
        status = st.session_state[status_key]
        is_done = status == "approved"
        is_rejected = status == "rejected"
        row_class = "done" if is_done else "rejected" if is_rejected else ""
        pill_class = "locked" if blocked_item else approval_status_class(status)
        status_copy = "Chưa mở" if blocked_item else approval_status_label(status, approval_id)
        reject_reason = st.session_state.get(_reject_reason_key(approval_id), "")
        consequence = APPROVAL_REJECT_CONSEQUENCES.get(approval_id, "")
        copy = subtitle
        if blocked_item:
            copy = f"{subtitle} · chỉ mở sau AP-2 và AP-3" if approval_id == "AP-4" else subtitle
        elif is_rejected:
            reason_suffix = f" Lý do: {reject_reason}." if reject_reason else ""
            copy = f"{consequence}{reason_suffix}"
        info, action = st.columns([0.68, 0.32], vertical_alignment="center")
        info.markdown(
            f'''<div class="approval-queue-row {row_class}">
                <div class="approval-queue-title">{esc(title)} <span class="approval-pill {pill_class}">{esc(status_copy)}</span></div>
                <div class="approval-queue-copy">{esc(copy)}</div>
            </div>''',
            unsafe_allow_html=True,
        )
        if blocked_item:
            action.button(
                f"Duyệt {approval_id}",
                width="stretch",
                disabled=True,
                key=approve_key,
            )
            return
        if st.session_state.rejecting_approval_id == approval_id:
            with action:
                _render_reject_confirmation(approval_id)
            return
        if status in {"approved", "rejected"}:
            if action.button(
                "Xem lại lựa chọn",
                width="stretch",
                key=f"review_{approval_id.lower().replace('-', '')}",
            ):
                _clear_approval_and_dependents(approval_id)
                st.rerun()
            return
        approve_col, reject_col = action.columns(2)
        if approve_col.button(
            f"Duyệt {approval_id}",
            width="stretch",
            key=approve_key,
        ):
            _set_approval_status(approval_id, "approved")
            st.rerun()
        if reject_col.button(
            "Không duyệt",
            width="stretch",
            key=f"reject_{approval_id.lower().replace('-', '')}",
        ):
            st.session_state.rejecting_approval_id = approval_id
            st.rerun()

    ap1_done = st.session_state.ap1_status == "approved"
    ap2_done = st.session_state.ap2_status == "approved"
    ap3_done = st.session_state.ap3_status == "approved"
    ap4_done = st.session_state.ap4_status == "approved"
    ap23_done = ap1_done and ap2_done and ap3_done
    approval_by_id = {
        str(item.get("id")): item for item in decision_card.get("approval_required", [])
    }

    st.markdown('<div class="approval-queue"></div>', unsafe_allow_html=True)
    st.markdown("#### Hàng chờ phê duyệt")
    st.markdown(
        '<div class="approval-queue-intro">Đây là khu vực thao tác duy nhất. Mỗi bước chỉ mở khi các điều kiện trước đó đã hoàn tất.</div>',
        unsafe_allow_html=True,
    )
    if not ap1_done:
        _render_approval_row(
            "AP-1",
            "AP-1 · Tạm giữ TXN-006/007",
            f"{money(risk.transaction_hold_amount_vnd)} · Founder xác nhận giữ giao dịch để mở gói quyết định.",
            False,
            "approve_ap1",
        )
        return

    approval_items = [
        (
            "AP-1 · Tạm giữ TXN-006/007",
            money(approval_by_id.get("AP-1", {}).get("amount")),
            "approve_ap1_done",
            True,
            False,
        ),
        (
            "AP-2 · Vốn lưu động CR-001",
            money(approval_by_id.get("AP-2", {}).get("amount")),
            "approve_ap2",
            ap2_done,
            False,
        ),
        (
            "AP-3 · Bảo lãnh thực hiện CR-002",
            money(approval_by_id.get("AP-3", {}).get("amount")),
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
        approval_id = key.removeprefix("approve_").removesuffix("_done").upper().replace("AP", "AP-")
        _render_approval_row(approval_id, title, subtitle, blocked_item, key)
    if not ap23_done:
        st.caption("AP-4 chỉ mở sau khi AP-2 và AP-3 cùng hoàn tất.")


def render_hold_card() -> None:
    st.markdown(
        f'<div class="hold-card"><strong>CR-003 · trade finance — HOLD</strong><br>'
        f'Eligibility {esc(credit_case_score_text("CR-003"))} · Supplier confirmation: MISSING. '
        f'Không ảnh hưởng CR-001/CR-002 trong gói chính.</div>',
        unsafe_allow_html=True,
    )


def _record_final_decision(
    final_state: str,
    approval_id: str,
    toast_message: str,
) -> None:
    """Apply AP-5 before Streamlit rerenders so stale decision buttons disappear."""
    st.session_state.final_state = final_state
    st.session_state.human_approval_id = approval_id
    st.session_state.action_warning = None
    st.session_state.action_toast = toast_message


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
    if st.session_state.final_state in FINAL_STATES:
        st.info(
            "AP-5 đã được Founder chốt. Quyết định được khóa để bảo toàn lịch sử phê duyệt; xem banner đầu Zone 2 và Runtime Log để đối chiếu."
        )
        return

    st.markdown("##### AP-5 · Founder chốt quyết định cuối")
    st.caption(
        "Chọn đúng một hướng xử lý. Mỗi lựa chọn sẽ cập nhật ngay banner Zone 2 và KPI trạng thái ở Zone 1."
    )
    actions = st.columns(4)
    actions[0].button(
        "Phê duyệt",
        type="primary",
        width="stretch",
        key="final_approve",
        on_click=_record_final_decision,
        args=("ACTIVE", "APR-FINAL-APPROVE", "Đã duyệt gói đề xuất."),
    )
    actions[1].button(
        "Từ chối",
        width="stretch",
        key="final_reject",
        on_click=_record_final_decision,
        args=("REJECTED", "APR-FINAL-REJECT", "Đã ghi nhận quyết định từ chối."),
    )
    actions[2].button(
        "Yêu cầu thêm thông tin",
        width="stretch",
        key="final_need_info",
        on_click=_record_final_decision,
        args=(
            "NEED_MORE_INFORMATION",
            "APR-NEEDINFO-001",
            "Đã yêu cầu bổ sung thông tin.",
        ),
    )
    actions[3].button(
        "Đàm phán lại",
        width="stretch",
        key="final_renegotiate",
        on_click=_record_final_decision,
        args=(
            "RENEGOTIATE",
            "APR-FINAL-RENEGOTIATE",
            "Đã chuyển hồ sơ sang đàm phán lại.",
        ),
    )


if page == "Tổng quan":
    render_snapshot_panel(
        snapshot_cards_for_view(detail_contract_id, overview_copy=True)
    )
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
            visible_summary = visible_summary.rename(
                columns={
                    "contract_id": "Contract ID",
                    "status": "Trạng thái",
                    "contract_value_vnd": "Giá trị hợp đồng (VND)",
                    "gross_margin": "Biên lợi nhuận",
                    "agent_priority": "Mức ưu tiên",
                    "reason": "Lý do",
                }
            )
            if "Biên lợi nhuận" in visible_summary.columns:
                visible_summary["Biên lợi nhuận"] = visible_summary[
                    "Biên lợi nhuận"
                ].map(
                    lambda value: f"{float(value) * 100:.1f}%"
                    if pd.notna(value)
                    else "n/a"
                )
            st.dataframe(visible_summary, width="stretch", hide_index=True)
            st.caption(f"Đang hiển thị {len(summary)}/{len(contract_ids)} hợp đồng. Customer ID đã được token hóa ở lớp dữ liệu.")
        with tab_credit:
            credit_show = _tokenize_df(credit_df, ["company_id", "customer_id"])
            if not credit_show.empty and selected_contract != "Tất cả hợp đồng":
                credit_show = related_credit_cases(selected_contract)
            credit_cols = [col for col in ["credit_case_id", "request_type", "requested_amount_vnd", "eligibility_score", "precheck_note", "approval_status"] if col in credit_show.columns]
            takeaway_title, takeaway_body = overview_credit_takeaway(
                selected_contract,
                credit_show,
            )
            info_card(takeaway_title, takeaway_body)
            credit_visible = credit_show[credit_cols].rename(
                columns={
                    "credit_case_id": "Credit Case ID",
                    "request_type": "Mục đích vay",
                    "requested_amount_vnd": "Số tiền đề nghị (VND)",
                    "eligibility_score": "Điểm sẵn sàng",
                    "precheck_note": "Ghi chú sơ bộ",
                    "approval_status": "Trạng thái duyệt",
                }
            )
            st.dataframe(credit_visible, width="stretch", hide_index=True)
            st.caption("Insight phía trên thay đổi theo hợp đồng được chọn; bảng giữ dữ liệu nguồn để Founder đối chiếu.")
        with tab_source:
            audit = backend.finance.source_audit
            source_rows = pd.DataFrame(
                [
                    {"Nguồn dữ liệu": key, "Số bản ghi": value}
                    for key, value in audit.row_counts.items()
                ]
            )
            st.dataframe(source_rows, width="stretch", hide_index=True)
            st.caption("Tổng 14 sheet đã nạp; các agent dùng chung một phần nguồn nên tổng theo agent không cộng trực tiếp.")

elif page == "Chi tiết hợp đồng":
    contract_row = selected_contract_row(detail_contract_id)
    order_rows = related_orders(detail_contract_id)
    invoice_rows = related_invoices(order_rows)
    margin = margin_for_contract(detail_contract_id)
    exec_risks = execution_risks_for_contract(detail_contract_id)
    contract_rec, contract_rationale = recommendation_for_contract(detail_contract_id)
    analysis_done = detail_contract_id != "CON-004" or con004_analysis_done()
    detail_state = (
        "CHỜ PHÂN TÍCH"
        if detail_contract_id == "CON-004" and not analysis_done
        else decision_card["state"]
        if detail_contract_id == "CON-004"
        else contract_status(detail_contract_id)[0]
    )
    blocked = (
        detail_contract_id == "CON-004"
        and analysis_done
        and st.session_state.ap1_status != "approved"
        and risk.financial_flow_paused
    )
    founder_insight_mode = str(
        founder_insights.get("llm_meta", {}).get("mode", "fallback")
    )
    founder_insight_source = (
        "OPENAI · LIVE"
        if founder_insight_mode == "live"
        else "DỰ PHÒNG · DỮ LIỆU ĐÃ KIỂM CHỨNG"
    )

    render_snapshot_panel(snapshot_cards_for_view(detail_contract_id))
    main_col, evidence_col = st.columns([0.76, 0.24], gap="medium")

    with main_col:
        with st.container(border=True):
            zone_heading("ZONE 2", "Contract Detail — Decision & Approval Flow")
            render_stepper(detail_state)
            render_contract_heading(detail_contract_id, contract_row, detail_state)
            if detail_contract_id == "CON-004":
                render_final_state_banner(
                    st.session_state.final_state,
                    st.session_state.human_approval_id,
                )

            # The backend analysis is already cached. On first entry, stop the
            # frontend here so the Founder explicitly sees ANALYZE happen before
            # the app reveals agent evidence or approval controls.
            if detail_contract_id == "CON-004" and not analysis_done:
                render_analysis_launcher()
                st.stop()

            if detail_contract_id == "CON-004":
                render_founder_approval_progress()
            if selected_contract == "Tất cả hợp đồng":
                st.info(
                    f"Portfolio đang được chọn; màn chi tiết mở {detail_contract_id} làm case demo mặc định. "
                    "Chọn một hợp đồng trong sidebar để chuyển phạm vi."
                )

            if blocked:
                st.markdown(
                    f'''<div class="state-box">
                        <div class="blocker-head">
                            <div style="display:flex;gap:8px;align-items:center">
                                <img src="{WARNING_URI}" alt="Cảnh báo" style="width:18px;height:18px;object-fit:contain" />
                                <span class="blocker-kicker">Điểm duyệt AP-1</span>
                            </div>
                            <span class="insight-source">{esc(founder_insight_source)}</span>
                        </div>
                        <div class="blocker-title">BLOCKED BY CRITICAL RISK — NGHI NGỜ GIAN LẬN</div>
                        <div class="blocker-copy">{esc(founder_insights.get("blocker_situation"))}</div>
                        <div class="blocker-action"><strong>Founder cần làm:</strong> {esc(founder_insights.get("blocker_action"))}</div>
                    </div>''',
                    unsafe_allow_html=True,
                )
            if detail_contract_id == "CON-004":
                render_gate_reason_kpis(decision_card)
            if detail_contract_id == "CON-004":
                st.markdown(
                    f'''<div class="analysis-overview-title">
                        <span>Kết quả phân tích sức khỏe tài chính tổng thể của OPC</span>
                        <span class="insight-source">{esc(founder_insight_source)}</span>
                    </div>''',
                    unsafe_allow_html=True,
                )
            agent_left, agent_right = st.columns(2, gap="medium")
            with agent_left:
                if agent_visible("Finance & Data"):
                    with st.container(border=True):
                        if analysis_done:
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
                                worst_month_value = (
                                    worst_period.month if worst_period else ""
                                )
                                worst_month_display = (
                                    f"{worst_month_value[5:7]}/{worst_month_value[:4]}"
                                    if len(worst_month_value) == 7
                                    and worst_month_value[4] == "-"
                                    else worst_month_value or selected_period
                                )
                                credit_priority_items = [
                                    credit_priority_item("CR-004", "đủ điều kiện, nên làm trước"),
                                    credit_priority_item("CR-001", "đủ điều kiện"),
                                    credit_priority_item("CR-002", "cần thêm bằng chứng dòng tiền"),
                                    credit_priority_item("CR-003", "chưa đủ điều kiện, đang treo"),
                                ]
                                credit_priority_html = "".join(
                                    f"<li>{esc(item)}</li>" for item in credit_priority_items
                                )
                                st.markdown(
                                    f'''<div class="agent-kpi-grid">
                                        <div class="agent-kpi-card">
                                            <div class="agent-kpi-label">Số tiền thiếu cho vận hành</div>
                                            <div class="agent-kpi-value">{esc(money(worst_period.funding_need_vnd) if worst_period else "n/a")}</div>
                                            <div class="agent-kpi-note">Tháng {esc(worst_month_display)}</div>
                                        </div>
                                        <div class="agent-kpi-card danger">
                                            <div class="agent-kpi-label">Biên lợi nhuận thấp nhất</div>
                                            <div class="agent-kpi-value">{esc(gross_margin_text)}</div>
                                            <div class="agent-kpi-note">CON-004 · ngưỡng {float(target_margin) * 100:.0f}%</div>
                                        </div>
                                        <div class="agent-kpi-card">
                                            <div class="agent-kpi-label">Gói tín dụng đủ điều kiện</div>
                                            <div class="agent-kpi-value">CR-004 → CR-001</div>
                                            <div class="agent-kpi-note">Ưu tiên theo mức sẵn sàng</div>
                                        </div>
                                    </div>
                                    <ul class="agent-insight-list">
                                        <li><strong>Nhu cầu vốn:</strong> {esc(founder_insights.get("finance_funding"))}</li>
                                        <li><strong>Khả năng sinh lời:</strong> {esc(founder_insights.get("finance_margin"))}</li>
                                        <li><strong>Phương án tín dụng:</strong> {esc(founder_insights.get("finance_credit"))}
                                            <ol class="credit-priority-list">
                                                {credit_priority_html}
                                            </ol>
                                        </li>
                                    </ul>''',
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
                        if analysis_done:
                            st.markdown("##### Risk & Compliance Agent")
                            if detail_contract_id == "CON-004":
                                st.markdown(
                                    f'''<div class="agent-kpi-grid">
                                        <div class="agent-kpi-card danger">
                                            <div class="agent-kpi-label">Mức phạt nếu giao trễ</div>
                                            <div class="agent-kpi-value">{esc(money(founder_insight_facts.get("ord004_penalty_vnd_per_day")))}/ngày</div>
                                            <div class="agent-kpi-note">ORD-004 · ngưỡng 7 ngày</div>
                                        </div>
                                        <div class="agent-kpi-card">
                                            <div class="agent-kpi-label">Gói tín dụng bị giữ lại</div>
                                            <div class="agent-kpi-value">CR-003</div>
                                            <div class="agent-kpi-note">Thiếu xác nhận từ nhà cung cấp</div>
                                        </div>
                                    </div>
                                    <ul class="agent-insight-list">
                                        <li><strong>Giao dịch rủi ro cao:</strong> {esc(founder_insights.get("risk_transaction"))}</li>
                                        <li><strong>Rủi ro từ đơn hàng:</strong> {esc(founder_insights.get("risk_order"))}</li>
                                        <li><strong>Rủi ro gói tín dụng:</strong> {esc(founder_insights.get("risk_credit"))}</li>
                                    </ul>''',
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
                if st.session_state.ap1_status == "approved":
                    render_cashflow_credit_data(detail_contract_id, decision_card)
                    render_cashflow_credit_insights(decision_card, backend)
                if agent_visible("Decision & Partner"):
                    render_decision_partner_card(decision_card, backend)
                    render_decision_partner_technical(decision_card)
                if not blocked:
                    render_decision_card(decision_card)
            elif agent_visible("Decision & Partner"):
                with st.expander("Decision & Partner Agent · bằng chứng bổ sung", expanded=False):
                    cases = related_credit_cases(detail_contract_id)
                    if cases.empty:
                        st.info("Workbook chưa có credit case chuyên biệt cho hợp đồng này.")
                    else:
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

            if detail_contract_id != "CON-004":
                render_cashflow_credit_data(detail_contract_id, decision_card)

            st.markdown("---")
            if detail_contract_id != "CON-004":
                st.info(
                    "CON-004 là case được kiểm chứng end-to-end theo yêu cầu demo. "
                    "Hợp đồng hiện tại giữ ở precheck vì workbook chưa có approval workflow riêng."
                )
            else:
                if analysis_done:
                    render_stage_approval_controls()
                    render_bank_api_sandbox()
                    render_final_decision_controls()
                    render_runtime_export(decision_card)

    with evidence_col:
        with st.container(border=True):
            zone_heading("ZONE 3", "System Evidence")
            render_runtime_evidence(decision_card)
            st.markdown(
                '<div class="mono" style="font-size:10px;color:#596273;margin:2px 0 6px">OpenAI Evidence</div>',
                unsafe_allow_html=True,
            )
            render_openai_evidence(decision_card)
            if detail_contract_id == "CON-004" and analysis_done:
                render_bank_api_failure_tester()
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



