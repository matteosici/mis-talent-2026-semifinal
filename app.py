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

st.set_page_config(page_title="Dashboard AI Agent OPC", layout="wide", page_icon="OPC")
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
        return "không áp dụng"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B VND"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.0f}M VND"
    return f"{value:,.0f} VND"


@st.cache_data(show_spinner="Đang đọc Team Pack Excel trực tiếp...")
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
    st.session_state.final_state = "BỊ CHẶN_BY_AP1" if backend.risk.financial_flow_paused else "DECISION_READY"
if "human_approval_id" not in st.session_state:
    st.session_state.human_approval_id = None

use_openai = st.sidebar.toggle("Dùng OpenAI live", value=True, help="Tự chuyển sang bản dự phòng nếu thiếu OPENAI_API_KEY hoặc API lỗi.")
page = st.sidebar.radio("Màn hình", ["Tổng quan", "Chi tiết CON-004", "Bằng chứng hệ thống"], index=0)

st.title("Dashboard AI Agent OPC")
st.markdown(
    '<span class="badge good">DỮ LIỆU: EXCEL LIVE</span>'
    f'<span class="badge {"good" if use_openai else "warn"}">OPENAI: {"LIVE/FALLBACK" if use_openai else "FALLBACK"}</span>'
    '<span class="badge blue">BANK API: MOCK / SANDBOX</span>',
    unsafe_allow_html=True,
)
st.caption(f"Tệp Excel: {WORKBOOK.name} | Mã hash dữ liệu: {workbook_hash} | Thời điểm phân tích: {loaded_at}")

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

if page == "Tổng quan":
    st.subheader("Dữ liệu đầu vào & Bức tranh kinh doanh")
    audit = backend.finance.source_audit
    total_records = sum(audit.row_counts.values()) if audit else 0
    cols = st.columns(4)
    cols[0].metric("Sheet DS1 đã đọc", f"{len(audit.loaded_sheets)}/8 sheet lõi")
    cols[1].metric("Bản ghi đã kiểm tra", f"{total_records}")
    cols[2].metric("Lỗi schema", "0" if audit.core_complete else len(audit.missing_sheets))
    cols[3].metric("Kiểm tra nguồn", "ĐẠT" if audit.core_complete else "BỊ CHẶN")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vi phạm mức tiền dự trữ", f"{backend.finance.cashflow.breach_count}/{len(backend.finance.cashflow.months)} months")
    c2.metric("Gói vốn đề xuất", money(finance.decision_package_total_ask_vnd), finance.worst_month)
    c3.metric("Cụm giao dịch Critical", money(risk.transaction_hold_amount_vnd), "TXN-006 / TXN-007")
    active_candidates = [x for x in backend.finance.credit_candidates if x.candidate_status != "hold"]
    held_candidates = [x for x in backend.finance.credit_candidates if x.candidate_status == "hold"]
    c4.metric("Hồ sơ tín dụng", f"{len(active_candidates)} đang xét / {len(held_candidates)} tạm giữ")

    left, right = st.columns([0.55, 0.45])
    with left:
        st.markdown("#### Số dòng dữ liệu live")
        st.dataframe(pd.DataFrame([{"sheet": k, "rows": v} for k, v in audit.row_counts.items()]), use_container_width=True, hide_index=True)
    with right:
        st.markdown("#### Ưu tiên hợp đồng")
        contracts = pd.DataFrame(team_pack.get("04_CONTRACTS", []))
        if not contracts.empty:
            wanted = [col for col in ["contract_id", "status", "contract_value", "gross_margin"] if col in contracts.columns]
            show = contracts[wanted].copy()
            show["priority"] = show["contract_id"].apply(lambda x: "1 - CRITICAL" if x == "CON-004" else "theo dõi")
            st.dataframe(show.sort_values("priority"), use_container_width=True, hide_index=True)
        st.info("Thao tác demo: chọn Chi tiết CON-004 ở sidebar để drill-down vào luồng phê duyệt live.")

elif page == "Chi tiết CON-004":
    st.subheader("Chi tiết CON-004 - Không gian quyết định 3 vùng")
    z1, z2, z3 = st.columns([0.25, 0.35, 0.40], gap="medium")

    with z1:
        st.markdown("### Vùng 1")
        st.caption("Các panel bằng chứng gốc")
        st.markdown("**Sức khỏe dữ liệu**")
        st.write(f"Đã đọc 8/8 sheet lõi DS1: `{backend.finance.source_audit.core_complete}`")
        st.write(f"Mã hash dữ liệu: `{workbook_hash}`")
        st.write(f"Thời điểm: `{loaded_at}`")
        st.markdown("**Bằng chứng đã che giấu**")
        st.json({note.field_name: note.tokenized_value or note.masked_value for note in backend.risk.safe_handling_notes})
        with st.expander("Dòng dữ liệu cashflow"):
            st.dataframe(pd.DataFrame([m.model_dump() for m in backend.finance.cashflow.months]), use_container_width=True)
        with st.expander("Giao dịch ngân hàng bị flag"):
            st.dataframe(pd.DataFrame([x.model_dump() for x in backend.risk.transaction_findings]), use_container_width=True)

    with z2:
        st.markdown("### Vùng 2")
        st.caption("Luồng xử lý agent")
        blocked = st.session_state.ap1_status != "approved" and risk.financial_flow_paused
        st.markdown(
            f'<div class="state-box {"" if blocked else "state-ok"}"><b>Trạng thái hợp nhất:</b> '
            f'{"BỊ CHẶN BỞI RỦI RO CRITICAL" if blocked else "AP-1 ĐÃ XỬ LÝ - SẴN SÀNG RA QUYẾT ĐỊNH"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("**Agent Tài chính & Dữ liệu**")
        st.write(f"Tháng xấu nhất: `{finance.worst_month}` | Gói vốn cần duyệt: **{money(finance.decision_package_total_ask_vnd)}**")
        st.write(f"Hóa đơn đang mở: **{money(finance.open_invoices_total_vnd)}** | Cảnh báo biên lợi nhuận: `{', '.join(finance.margin_warning_contract_ids)}`")
        st.markdown("**Agent Rủi ro & Tuân thủ**")
        txn_ids = risk.transaction_hold.txn_ids if risk.transaction_hold else []
        st.write(f"Cụm RR-001: `{', '.join(txn_ids)}` | Giá trị rủi ro: **{money(risk.transaction_hold_amount_vnd)}**")
        st.write(f"Luồng tài chính đang tạm dừng: `{risk.financial_flow_paused}` | Rủi ro triển khai: `{', '.join(risk.execution_risk_order_ids)}`")
        st.markdown("**Agent Quyết định & Đối tác**")
        st.dataframe(pd.DataFrame(decision_card["bank_fit_matrix"]), use_container_width=True, hide_index=True)
        st.warning("CR-003 đang bị giữ lại vì thiếu xác nhận nhà cung cấp. Agent yêu cầu bổ sung thông tin và không tự bịa bằng chứng.")

    with z3:
        st.markdown("### Vùng 3")
        st.caption("Hỗ trợ quyết định")
        tab1, tab2, tab3 = st.tabs(["Khuyến nghị", "Dòng tiền", "Gói tín dụng"])
        with tab1:
            if blocked:
                st.error("Thẻ quyết định đang bị khóa. Cần duyệt AP-1 trước để tiếp tục.")
            st.metric("Khuyến nghị", decision_card["recommendation"])
            st.write(decision_card["rationale"])
            st.markdown("**Điều kiện**")
            for condition in decision_card["conditions"]:
                st.write(f"- {condition}")
            st.markdown("**Mâu thuẫn phát hiện**")
            st.json(decision_card["conflicts_detected"])
        with tab2:
            cash = pd.DataFrame([m.model_dump() for m in backend.finance.cashflow.months])
            st.line_chart(cash.set_index("month")[["funding_need_vnd", "reserve_gap_vnd"]])
        with tab3:
            st.metric("Nhu cầu vốn", money(decision_card["financial_ask"]["total"]))
            st.metric("Tổng tài sản đảm bảo", money(decision_card["financial_ask"]["collateral_total"]))
            st.dataframe(pd.DataFrame(decision_card["financial_ask"]["breakdown"]), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("#### Hàng chờ phê duyệt")
        st.dataframe(pd.DataFrame(decision_card["approval_required"]), use_container_width=True, hide_index=True)
        a, b = st.columns(2)
        if a.button("Duyệt AP-1 tạm giữ", type="primary", use_container_width=True):
            st.session_state.ap1_status = "approved"
            st.session_state.final_state = "DECISION_READY"
            st.session_state.human_approval_id = "APR-001"
            st.rerun()
        if b.button("Yêu cầu bổ sung thông tin", use_container_width=True):
            st.session_state.final_state = "NEED_MORE_INFORMATION"
            st.session_state.human_approval_id = "APR-NEEDINFO-001"
            st.rerun()
        c, d, e = st.columns(3)
        if c.button("Duyệt gói đề xuất", use_container_width=True):
            st.session_state.final_state = "ACTIVE"
            st.session_state.human_approval_id = "APR-FINAL-APPROVE"
            st.rerun()
        if d.button("Từ chối", use_container_width=True):
            st.session_state.final_state = "REJECTED"
            st.session_state.human_approval_id = "APR-FINAL-REJECT"
            st.rerun()
        if e.button("Đàm phán lại", use_container_width=True):
            st.session_state.final_state = "RENEGOTIATE"
            st.session_state.human_approval_id = "APR-FINAL-RENEGOTIATE"
            st.rerun()

        if st.button("Xuất runtime log mẫu", use_container_width=True):
            log_path = write_json(ROOT / "runtime_logs" / "sample_runtime_log.json", build_sample_runtime_log(decision_card))
            card_path = write_json(ROOT / "output" / "demo_decision_card.json", decision_card)
            st.success(f"Đã xuất {log_path.name} and {card_path.name}")

else:
    st.subheader("Bằng chứng hệ thống")
    st.markdown("#### Output backend")
    st.json(backend.model_dump(mode="json"))
    st.markdown("#### Thẻ quyết định")
    st.json(decision_card)
    st.markdown("#### Xem trước runtime log")
    st.json(build_sample_runtime_log(decision_card))





