from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.agents import run_ds1_backend
from src.decision_agent import CREDIT_TO_API, build_decision_card, call_bank_api_mock
from src.runtime_log import build_sample_runtime_log, write_json
from src.security import _stable_token
from src.team_pack import (
    DS1_CORE_SHEETS,
    DS1_REQUIRED_SHEETS,
    DS1_SUPPORTING_SHEETS,
    DEFAULT_WORKBOOK,
    load_team_pack,
)

ROOT = Path(__file__).parent
LOCAL_WORKBOOK = ROOT / DEFAULT_WORKBOOK
EXTERNAL_V3_WORKBOOK = ROOT.parent / "MISTalent2026_OPC_AgenticAI_TeamPack_v3.xlsx"
WORKBOOK = EXTERNAL_V3_WORKBOOK if EXTERNAL_V3_WORKBOOK.exists() else LOCAL_WORKBOOK
POLICY = ROOT / "config" / "policies.yaml"

STATE_LABELS = {
    "BLOCKED_BY_AP1": "⛔ Bị chặn bởi AP-1",
    "DECISION_READY": "Sẵn sàng ra quyết định",
    "ACTIVE": "✓ Đã duyệt",
    "REJECTED": "✕ Từ chối",
    "NEED_MORE_INFORMATION": "Cần bổ sung thông tin",
    "RENEGOTIATE": "Đàm phán lại",
}

st.set_page_config(page_title="Dashboard AI Agent OPC", layout="wide", page_icon="OPC")
st.markdown(
    """
<style>
html, body, [class*="css"] { font-family: "Source Sans Pro", Arial, sans-serif; }
.stApp { background: #ffffff; color: #1f2937; }
.block-container { padding-top: 1.25rem; padding-bottom: 2rem; max-width: 1260px; }
section[data-testid="stSidebar"] { background: #fbfbfc; border-right: 1px solid #eef0f3; }
h1 { letter-spacing: 0; color: #202633; font-weight: 800; font-size: 2.05rem; }
h2, h3 { letter-spacing: 0; color: #273142; }
.section-title { font-size: 25px; line-height: 1.25; font-weight: 800; color: #202633; margin: .25rem 0 1rem; }
.badge { display:inline-block; border:1px solid #d8dee8; border-radius:6px; padding:5px 9px; margin-right:7px; font-size:12px; font-weight:700; background:#fff; }
.good { color:#067647; border-color:#abefc6; background:#ecfdf3; }
.warn { color:#b54708; border-color:#fedf89; background:#fffaeb; }
.blue { color:#175cd3; border-color:#b2ddff; background:#eff8ff; }
.state-box { border-left:5px solid #ff4b4b; padding:11px 13px; background:#fff5f6; border-radius:7px; margin-bottom:12px; box-shadow: 0 1px 4px rgba(16,24,40,.04); }
.state-ok { border-left-color:#12b76a; background:#f3fff7; }
.metric-card { border:1px solid #eef0f3; border-radius:8px; padding:12px 14px; min-height:92px; box-shadow:0 2px 10px rgba(16,24,40,.04); overflow:hidden; }
.metric-blue { background:#f4f8ff; }
.metric-green { background:#f3fbf6; }
.metric-amber { background:#fff8ed; }
.metric-rose { background:#fff4f5; }
.metric-gray { background:#f8fafc; }
.metric-label { color:#475467; font-size:13px; font-weight:700; margin-bottom:8px; white-space:normal; }
.metric-value { color:#202633; font-size:26px; line-height:1.1; font-weight:800; letter-spacing:0; overflow-wrap:anywhere; }
.metric-delta { display:inline-block; color:#067647; background:#dff8e8; padding:2px 7px; border-radius:999px; font-size:12px; font-weight:700; margin-top:8px; }
.metric-delta-warn { color:#b54708; background:#ffefd0; }
div[data-testid="stMetric"] { background: #fff; border: 1px solid #eef0f3; border-radius: 8px; padding: 10px 12px; box-shadow: 0 2px 10px rgba(16,24,40,.04); }
.stButton > button { border-radius: 6px; border-color: #ff6b6b; color: #ff4b4b; font-weight: 700; }
.stButton > button[kind="primary"] { background: #ff4b4b; color: white; border-color: #ff4b4b; }
.stButton > button:disabled { border-color: #e5e7eb; color: #98a2b3; background: #f6f7f9; }
.stTabs [data-baseweb="tab-highlight"] { background-color: #ff4b4b; }
.stTabs [data-baseweb="tab"] { font-weight: 700; }
.rec-card { background:#fff; border:1px solid #eef0f3; border-radius:8px; padding:12px 14px; box-shadow: 0 2px 10px rgba(16,24,40,.04); margin-bottom: 12px; }
.rec-label { color:#475467; font-size:14px; font-weight:700; margin-bottom:4px; }
.rec-value { color:#202633; font-size:24px; line-height:1.15; font-weight:800; letter-spacing:0; overflow-wrap:anywhere; }
.rec-sub { color:#667085; font-size:12px; margin-top:4px; }
.sidebar-block { border-top:1px solid #eef0f3; padding-top:14px; margin-top:14px; }
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


def object_dump(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return obj
    return dict(getattr(obj, "__dict__", {}))


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
bank_products_df = df_from_sheet(team_pack, "11_BANK_PRODUCTS")
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
use_openai = st.sidebar.toggle("Dùng OpenAI live", value=True, help="Gọi GPT-4o tại Decision & Partner Agent sau khi AP-1 được duyệt. Có fallback nếu API lỗi.")
if os.getenv("OPENAI_API_KEY"):
    st.sidebar.caption("OpenAI key: đã có trong môi trường. Không hiển thị key trên UI.")
else:
    st.sidebar.caption("OpenAI key: chưa thấy trong môi trường. App sẽ chạy fallback an toàn.")

finance = backend.finance.d5_handoff
risk = backend.risk.d5_handoff
if finance is None or risk is None:
    st.error("Backend chưa tạo đủ handoff D5. Vui lòng chạy lại pipeline hoặc kiểm tra source audit.")
    st.stop()
initial_blocked = st.session_state.ap1_status != "approved" and backend.risk.financial_flow_paused
decision_card = build_decision_card(
    backend,
    team_pack,
    use_openai=use_openai and not initial_blocked,
    ap1_status=st.session_state.ap1_status,
    ap2_status=st.session_state.ap2_status,
    ap3_status=st.session_state.ap3_status,
    ap4_status=st.session_state.ap4_status,
    final_state=st.session_state.final_state,
    human_approval_id=st.session_state.human_approval_id,
)

llm_mode = decision_card.get("llm_meta", {}).get("mode", "fallback")
openai_label = {
    "live": "LIVE",
    "fallback": "DỰ PHÒNG",
    "fallback_after_invalid_schema": "DỰ PHÒNG: SCHEMA FAILED",
    "fallback_after_error": "DỰ PHÒNG SAU LỖI",
}.get(llm_mode, llm_mode.upper())
if initial_blocked:
    openai_label = "CHỜ AP-1"
openai_class = "good" if llm_mode == "live" and not initial_blocked else "warn"

st.title("Dashboard AI Agent OPC")
st.markdown(
    '<span class="badge good">DỮ LIỆU: EXCEL LIVE</span>'
    f'<span class="badge {openai_class}">OPENAI: {openai_label}</span>'
    '<span class="badge blue">BANK API: MOCK / SANDBOX</span>',
    unsafe_allow_html=True,
)
st.caption(f"Tệp Excel: {WORKBOOK.name} | Mã hash dữ liệu: {workbook_hash} | Thời điểm phân tích: {loaded_at}")
st.caption(f"Bộ lọc: {selected_period} · {selected_contract} · {agent_focus}")


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


if page == "Tổng quan":
    st.markdown('<div class="section-title">Dữ liệu đầu vào & Bức tranh kinh doanh</div>', unsafe_allow_html=True)
    audit = backend.finance.source_audit
    total_records = sum(audit.row_counts.values()) if audit else 0
    active_candidates = [x for x in backend.finance.credit_candidates if x.candidate_status != "hold"]
    held_candidates = [x for x in backend.finance.credit_candidates if x.candidate_status == "hold"]

    cols = st.columns(4)
    with cols[0]:
        required_loaded = sum(
            1 for sheet in DS1_REQUIRED_SHEETS if sheet in audit.loaded_sheets
        )
        metric_card(
            "Sheet DS1 đã đọc",
            f"{required_loaded}/{len(DS1_REQUIRED_SHEETS)}",
            f"{len(DS1_CORE_SHEETS)} lõi + {len(DS1_SUPPORTING_SHEETS)} hỗ trợ",
            "blue",
        )
    with cols[1]:
        metric_card("Bản ghi đã kiểm tra", f"{total_records}", None, "gray")
    with cols[2]:
        metric_card("Lỗi schema", "0" if audit.core_complete else str(len(audit.missing_sheets)), None, "green" if audit.core_complete else "rose")
    with cols[3]:
        metric_card("Kiểm tra nguồn", "ĐẠT" if audit.core_complete else "BỊ CHẶN", None, "green" if audit.core_complete else "rose")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Vi phạm mức tiền dự trữ", f"{backend.finance.cashflow.breach_count}/{len(backend.finance.cashflow.months)}", "tháng", "amber", warn=True)
    with c2:
        metric_card("Gói vốn đề xuất", money(finance.decision_package_total_ask_vnd), finance.worst_month, "blue")
    with c3:
        if risk_visible(risk.transaction_hold_severity):
            metric_card("Cụm giao dịch Critical", money(risk.transaction_hold_amount_vnd), "TXN-006 / TXN-007", "rose", warn=True)
        else:
            metric_card("Cụm giao dịch Critical", "đã lọc ẩn", "filter mức rủi ro", "gray")
    with c4:
        metric_card("Hồ sơ tín dụng", f"{len(active_candidates)} xét", f"{len(held_candidates)} tạm giữ", "green")

    left, right = st.columns([0.52, 0.48])
    with left:
        st.markdown("#### Số dòng dữ liệu live")
        st.dataframe(pd.DataFrame([{"sheet": k, "rows": v} for k, v in audit.row_counts.items()]), use_container_width=True, hide_index=True)
    with right:
        st.markdown("#### Tất cả hợp đồng")
        summary = contract_summary_table()
        st.dataframe(summary, use_container_width=True, hide_index=True)
        st.caption(f"Đang hiển thị {len(summary)}/{len(contract_ids)} hợp đồng theo filter `{selected_contract}`.")

    st.markdown("#### Tất cả credit case")
    credit_show = _tokenize_df(credit_df, ["company_id", "customer_id"])
    if not credit_show.empty and selected_contract != "Tất cả hợp đồng":
        credit_show = related_credit_cases(selected_contract)
    st.dataframe(credit_show, use_container_width=True, hide_index=True)

elif page == "Chi tiết hợp đồng":
    contract_row = selected_contract_row(detail_contract_id)
    order_rows = related_orders(detail_contract_id)
    invoice_rows = related_invoices(order_rows)
    margin = margin_for_contract(detail_contract_id)
    exec_risks = execution_risks_for_contract(detail_contract_id)
    contract_rec, contract_rationale = recommendation_for_contract(detail_contract_id)

    st.markdown(f'<div class="section-title">Chi tiết {detail_contract_id} - Không gian quyết định 3 vùng</div>', unsafe_allow_html=True)
    if selected_contract == "Tất cả hợp đồng":
        st.info(f"Bạn đang chọn toàn bộ portfolio; trang chi tiết đang mở mặc định {detail_contract_id}. Chọn từng hợp đồng ở sidebar để drill-down case khác.")
    z1, z2, z3 = st.columns([0.25, 0.35, 0.40], gap="medium")

    with z1:
        st.markdown("### Vùng 1")
        st.caption("Dữ liệu gốc và audit theo hợp đồng")
        st.markdown("**Hợp đồng đang xem**")
        safe_contract_row = _tokenize_record(contract_row, ["customer_id"])
        st.json({"contract_id": detail_contract_id, "customer": selected_customer_name(contract_row), **safe_contract_row})
        cols = st.columns(2)
        with cols[0]:
            metric_card("Order liên quan", str(len(order_rows)), None, "blue")
        with cols[1]:
            metric_card("Invoice liên quan", str(len(invoice_rows)), None, "green")
        st.markdown("**Sức khỏe dữ liệu**")
        st.write(
            "14/14 sheet DS1 (8 lõi + 6 hỗ trợ): "
            f"`{not backend.finance.source_audit.missing_sheets}`"
        )
        st.write(f"Mã hash dữ liệu: `{workbook_hash}`")
        with st.expander("Order của hợp đồng"):
            st.dataframe(order_rows, use_container_width=True, hide_index=True)
        with st.expander("Invoice của hợp đồng"):
            st.dataframe(
                _tokenize_df(invoice_rows, ["customer_id"]),
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Giao dịch ngân hàng bị flag"):
            st.dataframe(pd.DataFrame([x.model_dump() for x in backend.risk.transaction_findings]), use_container_width=True, hide_index=True)

    with z2:
        st.markdown("### Vùng 2")
        st.caption("Luồng xử lý agent")
        blocked = detail_contract_id == "CON-004" and st.session_state.ap1_status != "approved" and risk.financial_flow_paused
        st.markdown(
            f'<div class="state-box {"" if blocked else "state-ok"}"><b>Trạng thái hợp nhất:</b> '
            f'{"BỊ CHẶN BỞI RỦI RO CRITICAL" if blocked else "ĐANG THEO DÕI / SẴN SÀNG PHÂN TÍCH"}</div>',
            unsafe_allow_html=True,
        )
        if agent_visible("Finance & Data"):
            st.markdown("**Agent Tài chính & Dữ liệu**")
            fcols = st.columns(2)
            with fcols[0]:
                metric_card("Giá trị hợp đồng", money(contract_row.get("contract_value")), None, "blue")
            with fcols[1]:
                gm = margin.get("gross_margin")
                gm_text = f"{float(gm) * 100:.1f}%" if gm is not None and pd.notna(gm) else "không rõ"
                metric_card("Gross margin", gm_text, money(margin.get("gross_profit_vnd")), "green" if gm is not None and pd.notna(gm) and float(gm) >= 0.27 else "amber", warn=bool(gm is not None and pd.notna(gm) and float(gm) < 0.27))
            st.caption(f"Portfolio cashflow: tháng xấu nhất `{finance.worst_month}`, gói vốn đề xuất {money(finance.decision_package_total_ask_vnd)}.")
        if agent_visible("Risk & Compliance"):
            st.markdown("**Agent Rủi ro & Tuân thủ**")
            if detail_contract_id == "CON-004" and risk_visible(risk.transaction_hold_severity):
                txn_ids = risk.transaction_hold.txn_ids if risk.transaction_hold else []
                st.error(f"RR-001: cụm giao dịch {', '.join(txn_ids)} đang tạm giữ luồng tài chính ({money(risk.transaction_hold_amount_vnd)}).")
            if exec_risks:
                st.dataframe(pd.DataFrame(exec_risks), use_container_width=True, hide_index=True)
            else:
                st.success("Không có execution risk của hợp đồng trong filter hiện tại.")
        if agent_visible("Decision & Partner"):
            st.markdown("**Agent Quyết định & Đối tác**")
            cases = related_credit_cases(detail_contract_id)
            if not cases.empty:
                st.dataframe(cases, use_container_width=True, hide_index=True)
            else:
                st.info("Workbook chưa có credit case chuyên biệt cho hợp đồng này.")
            if detail_contract_id == "CON-004" and not blocked:
                st.dataframe(pd.DataFrame(decision_card["bank_fit_matrix"]), use_container_width=True, hide_index=True)
                st.markdown("**OpenAI/GPT-4o reasoning**")
                st.json(decision_card.get("llm_meta", {}))
            elif detail_contract_id != "CON-004":
                st.caption("Decision Card đầy đủ/AP queue chỉ có dữ liệu sâu cho CON-004; các hợp đồng khác đang hiển thị precheck từ Finance/Risk/credit case.")

    with z3:
        st.markdown("### Vùng 3")
        st.caption("Hỗ trợ quyết định")
        if detail_contract_id == "CON-004":
            st.metric(
                "Trạng thái",
                STATE_LABELS.get(
                    decision_card["state"],
                    decision_card["state"],
                ),
            )
        tab1, tab2, tab3 = st.tabs(["Khuyến nghị", "Dòng tiền", "Gói tín dụng"])
        with tab1:
            if detail_contract_id == "CON-004" and blocked:
                st.error("Thẻ quyết định đang bị khóa. Cần duyệt AP-1 trước để tiếp tục.")
                st.caption("Ở trạng thái BLOCKED_BY_AP1, dashboard chỉ hiển thị output Finance/Risk và hàng chờ phê duyệt.")
            else:
                st.markdown(
                    f'''<div class="rec-card">
                        <div class="rec-label">Khuyến nghị</div>
                        <div class="rec-value">{contract_rec}</div>
                        <div class="rec-sub">Hợp đồng: {detail_contract_id}</div>
                    </div>''',
                    unsafe_allow_html=True,
                )
                st.write(contract_rationale)
                if detail_contract_id == "CON-004":
                    st.markdown("**Điều kiện**")
                    for condition in decision_card["conditions"]:
                        st.write(f"- {condition}")
                    st.markdown("**Mâu thuẫn phát hiện**")
                    st.json(decision_card["conflicts_detected"])
        with tab2:
            cash = pd.DataFrame([m.model_dump() for m in filtered_cashflow_rows()])
            st.line_chart(cash.set_index("month")[["funding_need_vnd", "reserve_gap_vnd"]])
        with tab3:
            cases = related_credit_cases(detail_contract_id)
            st.dataframe(cases, use_container_width=True, hide_index=True)
            if detail_contract_id == "CON-004" and not blocked:
                st.metric("Nhu cầu vốn theo Decision Card", money(decision_card["financial_ask"]["total"]))
                st.metric("Tổng tài sản đảm bảo", money(decision_card["financial_ask"]["collateral_total"]))
                st.dataframe(pd.DataFrame(decision_card["financial_ask"]["breakdown"]), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("#### Hàng chờ phê duyệt")
        if detail_contract_id != "CON-004":
            st.info("Approval queue AP-1 đến AP-5 trong prototype đang gắn với Decision Card CON-004. Hợp đồng này chưa có approval workflow riêng trong workbook.")
        else:
            approval_view = approval_rows_for_view()
            st.dataframe(pd.DataFrame(approval_view), use_container_width=True, hide_index=True)
            st.caption(f"Đang hiển thị {len(approval_view)}/{len(decision_card['approval_required'])} approval của Decision Card CON-004.")
            if st.session_state.action_warning:
                st.warning(st.session_state.action_warning)
            ap_cols = st.columns(4)
            if ap_cols[0].button("Duyệt AP-1 tạm giữ", type="primary", use_container_width=True, disabled=st.session_state.ap1_status == "approved"):
                st.session_state.ap1_status = "approved"
                st.session_state.final_state = "DECISION_READY"
                st.session_state.human_approval_id = "APR-001"
                st.session_state.action_warning = None
                st.session_state.action_toast = "Đã duyệt AP-1 và mở khóa luồng quyết định."
                st.rerun()
            ap1_done = st.session_state.ap1_status == "approved"
            if ap_cols[1].button("Duyệt AP-2 vốn lưu động", use_container_width=True, disabled=not ap1_done or st.session_state.ap2_status == "approved"):
                st.session_state.ap2_status = "approved"
                st.session_state.human_approval_id = "APR-002"
                st.session_state.action_warning = None
                st.session_state.action_toast = "Đã duyệt AP-2 vốn lưu động."
                st.rerun()
            if ap_cols[2].button("Duyệt AP-3 bảo lãnh", use_container_width=True, disabled=not ap1_done or st.session_state.ap3_status == "approved"):
                st.session_state.ap3_status = "approved"
                st.session_state.human_approval_id = "APR-003"
                st.session_state.action_warning = None
                st.session_state.action_toast = "Đã duyệt AP-3 bảo lãnh thực hiện."
                st.rerun()
            ap23_done = ap1_done and st.session_state.ap2_status == "approved" and st.session_state.ap3_status == "approved"
            if ap_cols[3].button("Duyệt AP-4 gửi hồ sơ", use_container_width=True, disabled=not ap23_done or st.session_state.ap4_status == "approved"):
                st.session_state.ap4_status = "approved"
                st.session_state.human_approval_id = "APR-004"
                st.session_state.action_warning = None
                st.session_state.action_toast = "Đã duyệt AP-4. Bank API sandbox đã được mở."
                st.rerun()

            all_prereq_done = ap23_done and st.session_state.ap4_status == "approved"
            next_step = "AP-1" if not ap1_done else "AP-2/AP-3" if not ap23_done else "AP-4" if st.session_state.ap4_status != "approved" else None
            final_cols = st.columns(4)
            if final_cols[0].button("Duyệt gói đề xuất", use_container_width=True, disabled=not all_prereq_done):
                st.session_state.final_state = "ACTIVE"
                st.session_state.human_approval_id = "APR-FINAL-APPROVE"
                st.session_state.action_warning = None
                st.session_state.action_toast = "Đã duyệt gói đề xuất."
                st.rerun()
            if final_cols[1].button("Từ chối", use_container_width=True, disabled=not all_prereq_done):
                st.session_state.final_state = "REJECTED"
                st.session_state.human_approval_id = "APR-FINAL-REJECT"
                st.session_state.action_warning = None
                st.session_state.action_toast = "Đã ghi nhận quyết định từ chối."
                st.rerun()
            if final_cols[2].button("Yêu cầu bổ sung thông tin", use_container_width=True):
                st.session_state.final_state = "NEED_MORE_INFORMATION"
                st.session_state.human_approval_id = "APR-NEEDINFO-001"
                st.session_state.action_warning = None
                st.session_state.action_toast = "Đã yêu cầu bổ sung thông tin."
                st.rerun()
            if final_cols[3].button("Đàm phán lại", use_container_width=True, disabled=not all_prereq_done):
                st.session_state.final_state = "RENEGOTIATE"
                st.session_state.human_approval_id = "APR-FINAL-RENEGOTIATE"
                st.session_state.action_warning = None
                st.session_state.action_toast = "Đã chuyển hồ sơ sang đàm phán lại."
                st.rerun()
            if not all_prereq_done and next_step:
                st.caption(f"Action blocked · Required next step: {next_step}")

            if st.session_state.ap4_status == "approved":
                st.markdown("#### Bank API sandbox theo BTC catalog")
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
                    "Hồ sơ tín dụng",
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
                    f"{catalog_row.get('endpoint', 'endpoint chưa khai báo')} · chỉ mô phỏng, không gửi ngân hàng thật"
                )
                simulated_status = st.selectbox(
                    "HTTP status mô phỏng",
                    [200, 400, 401, 409, 429, 503],
                    key="bank_api_status",
                )
                if st.button("Gọi Bank API mock", use_container_width=True):
                    candidate = candidate_by_id[selected_api_case]
                    st.session_state.bank_api_response = call_bank_api_mock(
                        selected_api_case,
                        candidate.requested_amount_vnd,
                        simulated_status,
                        api_catalog=team_pack.get("12_API_CATALOG", []),
                        sandbox_contracts=team_pack.get("22_SANDBOX_CONTRACT", []),
                    )
                    result = st.session_state.bank_api_response
                    if result["ok"]:
                        st.toast(f"{selected_api_id}: sandbox pre-check thành công.")
                    else:
                        st.toast(
                            f"{selected_api_id}: safe failure {result.get('error_code')}."
                        )
                if st.session_state.bank_api_response:
                    api_result = st.session_state.bank_api_response
                    if api_result["ok"]:
                        st.success(
                            "Sandbox trả về thành công; vẫn cần phê duyệt con người trước khi submit."
                        )
                    else:
                        st.warning(
                            f"Safe failure: {api_result.get('required_handling')}"
                        )
                    st.json(api_result)

        if st.button("Xuất runtime log mẫu", use_container_width=True):
            log_path = write_json(ROOT / "runtime_logs" / "sample_runtime_log.json", build_sample_runtime_log(decision_card))
            card_path = write_json(ROOT / "output" / "demo_decision_card.json", decision_card)
            st.success(f"Đã xuất {log_path.name} và {card_path.name}")

else:
    st.markdown('<div class="section-title">Bằng chứng hệ thống</div>', unsafe_allow_html=True)
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
    st.json(safe_backend_evidence)
    st.markdown("#### OpenAI GPT-4o trong chức năng lõi")
    st.json({
        "where_used": "Decision & Partner Agent - sinh rationale/conditions/conflict check cho Decision Card",
        "input": ["finance_handoff", "risk_handoff", "bank_fit_matrix"],
        "output": ["conflicts_detected", "conditions", "rationale"],
        "mode_runtime": decision_card.get("llm_meta", {}),
        "fallback_policy": (
            "Thiếu OPENAI_API_KEY dùng deterministic fallback; output sai schema ghi "
            "fallback_after_invalid_schema/FAILED; lỗi trước validate ghi "
            "fallback_after_error/NOT_RUN."
        ),
    })
    st.markdown("#### Thẻ quyết định CON-004")
    st.json(decision_card)
    st.markdown("#### Xem trước runtime log")
    st.json(build_sample_runtime_log(decision_card))


