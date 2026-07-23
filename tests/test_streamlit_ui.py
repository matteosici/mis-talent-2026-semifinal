from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from streamlit.testing.v1 import AppTest


APP = Path(__file__).parents[1] / "app.py"


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=60).run()


def _button(app: AppTest, key: str):
    return next(item for item in app.button if item.key == key)


def _advance_to_ap4(app: AppTest) -> AppTest:
    app.radio[0].set_value("Chi tiết hợp đồng").run()
    _button(app, "analyze_con004").click().run()
    _button(app, "approve_ap1").click().run()
    _button(app, "approve_ap2").click().run()
    _button(app, "approve_ap3").click().run()
    _button(app, "approve_ap4").click().run()
    return app


def _install_openai_stub(monkeypatch) -> dict[str, int]:
    calls = {"create": 0}
    decision_payload = {
        "conflicts_detected": [
            {
                "description": "conflict",
                "resolution_note": "resolution",
            }
        ],
        "conditions": ["condition"],
        "rationale": "rationale",
    }
    founder_payload = {
        "blocker_situation": "TXN-006/TXN-007 tạo rủi ro trực tiếp cho Founder.",
        "blocker_action": "Giữ CON-004 và xử lý AP-1 trước bước tiếp theo.",
        "finance_funding": "CON-004 cần xử lý thiếu hụt vốn trước tháng căng nhất.",
        "finance_margin": "CON-004 cần rà lại giá và chi phí.",
        "finance_credit": "Ưu tiên CR-004, CR-001; bổ sung CR-002 và giữ CR-003.",
        "risk_transaction": "TXN-006/TXN-007 đã được chặn.",
        "risk_order": "ORD-004 của CON-003 cần can thiệp để tránh phạt.",
        "risk_credit": "CR-003 của CON-005 cần xác nhận nhà cung cấp.",
    }

    class FakeResponses:
        def create(self, **kwargs):
            calls["create"] += 1
            schema_name = kwargs.get("text", {}).get("format", {}).get("name")
            payload = (
                founder_payload
                if schema_name == "founder_business_insights"
                else decision_payload
            )
            return type(
                "FakeResponse",
                (),
                {
                    "id": f"resp-test-{calls['create']}",
                    "output_text": json.dumps(payload),
                },
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    module = ModuleType("openai")
    module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4")
    return calls


def test_overview_filters_render_without_exposing_raw_code(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = _app()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "Tổng số sheet đã đọc" in markup
    assert "Data Health &amp; Business Snapshot" in markup
    assert "Finance 8 · Risk 12 · Decision 1" in markup
    assert "Mã đối soát nguồn" in markup
    assert "10 ký tự đầu của mã SHA-256" in markup
    assert "Ngưỡng tiêu chuẩn: 28%" in markup
    assert "Không đạt chuẩn" in markup
    assert "TAKEAWAY · CON-004" in markup

    assert list(app.dataframe[0].value.columns) == [
        "Contract ID",
        "Trạng thái",
        "Giá trị hợp đồng (VND)",
        "Biên lợi nhuận",
        "Mức ưu tiên",
        "Lý do",
    ]
    assert "Credit Case ID" in app.dataframe[1].value.columns
    assert "Điểm sẵn sàng" in app.dataframe[1].value.columns
    assert list(app.dataframe[2].value.columns) == ["Nguồn dữ liệu", "Số bản ghi"]

    contract = next(item for item in app.selectbox if item.label == "Hợp đồng trọng tâm")
    contract.set_value("CON-001").run()
    period = next(item for item in app.selectbox if item.label == "Kỳ phân tích")
    period.set_value("Quý hiện tại").run()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "3/3 tháng" in markup


def test_overview_wording_does_not_leak_into_contract_detail(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = _app()
    app.radio[0].set_value("Chi tiết hợp đồng").run()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "Trạng thái CON-004" in markup
    assert "CHỜ PHÂN TÍCH" in markup
    assert "Input hash" not in markup
    assert "Mã đối soát nguồn" not in markup
    assert "Finance 8 · Risk 12 · D&amp;P 1" in markup
    assert "TAKEAWAY · CON-004" not in markup


def test_contract_detail_starts_collapsed_and_approval_gates_work(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = _app()
    app.radio[0].set_value("Chi tiết hợp đồng").run()
    assert not app.exception
    assert "Dữ liệu hợp đồng đã token hóa" not in [item.label for item in app.expander]
    assert _button(app, "analyze_con004").disabled is False
    assert _button(app, "analyze_con004").label == "Phân tích chi tiết cho CON-004"
    assert not any(item.key == "approve_ap1" for item in app.button)
    markup = "\n".join(item.value for item in app.markdown)
    assert "Tiến độ Founder phê duyệt" not in markup
    assert "CHỜ PHÂN TÍCH" in markup
    assert "Kết quả phân tích sức khỏe tài chính tổng thể của OPC" not in markup

    _button(app, "analyze_con004").click().run()
    assert app.session_state["con004_analysis_status"] == "analyzed"
    assert "Dữ liệu hợp đồng đã token hóa" in [item.label for item in app.expander]
    assert _button(app, "approve_ap1").disabled is False
    assert not any(item.key in {"approve_ap2", "approve_ap3", "approve_ap4"} for item in app.button)
    assert not any(item.key == "final_approve" for item in app.button)
    markup = "\n".join(item.value for item in app.markdown)
    assert "Tiến độ Founder phê duyệt" in markup
    assert "Kết quả phân tích sức khỏe tài chính tổng thể của OPC" in markup
    assert "BLOCKED BY CRITICAL RISK — NGHI NGỜ GIAN LẬN" in markup
    assert "Founder cần làm:" in markup
    assert "Decision &amp; Partner đang chờ phản hồi từ Founder" in markup
    assert "Decision Card" not in markup
    assert "Dòng tiền &amp; Gói tín dụng" not in markup
    assert "Số tiền thiếu cho vận hành" in markup
    assert "Điểm rủi ro giao dịch" in markup
    assert "Giá trị giao dịch bị chặn" not in markup
    assert "TXN-006/007 cluster — exposure" not in markup

    _button(app, "approve_ap1").click().run()
    assert app.session_state["ap1_status"] == "approved"
    assert app.session_state["final_state"] == "CREDIT_PACKAGE_PROPOSED"
    assert "1/5" in "\n".join(item.value for item in app.markdown)
    markup = "\n".join(item.value for item in app.markdown)
    assert "Dòng tiền & Gói tín dụng" in markup
    assert "Tình huống cần xử lý" in markup
    assert "Gói vay chính gồm 2 khoản" in markup
    assert "Decision & Partner Agent · Bằng chứng bổ sung" in markup
    assert "Decision Card" in markup
    assert "Chưa duyệt · AP-2" in markup
    assert "Chưa duyệt · AP-3" in markup
    assert "Rủi ro và bằng chứng cần xử lý" in markup
    assert "Risks remaining" not in markup
    assert "Missing evidence" not in markup
    assert "Nếu Founder duyệt đủ các bước trên, OPC nhận lại gì?" in markup
    assert markup.index(
        "Kết quả phân tích sức khỏe tài chính tổng thể của OPC"
    ) < markup.index("Dòng tiền & Gói tín dụng") < markup.index(
        "Tình huống cần xử lý"
    ) < markup.index(
        "Decision & Partner Agent · Bằng chứng bổ sung"
    ) < markup.index("Decision Card ·") < markup.index("Hàng chờ phê duyệt")
    expander_labels = [item.label for item in app.expander]
    assert expander_labels.index("Dữ liệu hợp đồng đã token hóa") < expander_labels.index(
        "Bằng chứng kỹ thuật · Decision & Partner"
    )
    assert expander_labels[-1] == "Bằng chứng kỹ thuật · Decision & Partner"
    assert "Dữ liệu kỹ thuật · Dòng tiền & Gói tín dụng" not in expander_labels
    assert _button(app, "approve_ap2").disabled is False
    assert _button(app, "approve_ap3").disabled is False
    assert _button(app, "approve_ap4").disabled is True

    _button(app, "approve_ap2").click().run()
    markup = "\n".join(item.value for item in app.markdown)
    assert "Đã duyệt · AP-2" in markup
    assert "Chưa duyệt · AP-3" in markup
    _button(app, "approve_ap3").click().run()
    assert "3/5" in "\n".join(item.value for item in app.markdown)
    assert _button(app, "approve_ap4").disabled is False
    _button(app, "approve_ap4").click().run()
    assert app.session_state["ap4_status"] == "approved"
    assert app.session_state["final_state"] == "DECISION_READY"
    markup = "\n".join(item.value for item in app.markdown)
    assert "Hồ sơ đã qua AP-1 đến AP-4" in markup
    assert "AP-4 · Đã duyệt" in markup
    assert "Bank API sandbox" in markup
    assert _button(app, "final_approve").disabled is False

    _button(app, "call_bank_api").click().run()
    assert app.session_state["bank_api_response"]["ok"] is True
    assert not app.exception

    _button(app, "final_approve").click().run()
    assert app.session_state["final_state"] == "ACTIVE"
    assert app.session_state["human_approval_id"] == "APR-FINAL-APPROVE"
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "CON-004 đã được phê duyệt" in markup
    assert "Trạng thái CON-004" in markup
    assert "ACTIVE" in markup
    assert not any(item.key == "final_approve" for item in app.button)


def test_approval_reject_flow_is_reversible(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = _app()
    app.radio[0].set_value("Chi tiết hợp đồng").run()
    _button(app, "analyze_con004").click().run()
    _button(app, "approve_ap1").click().run()

    _button(app, "reject_ap2").click().run()
    app.selectbox(key="ap_2_reject_reason_select").set_value(
        "Chưa cần thiết ở giai đoạn này"
    ).run()
    _button(app, "confirm_reject_ap2").click().run()

    assert app.session_state["ap2_status"] == "rejected"
    assert app.session_state["ap2_reject_reason"] == "Chưa cần thiết ở giai đoạn này"
    assert app.session_state["human_approval_id"] == "APR-002-REJECT"
    markup = "\n".join(item.value for item in app.markdown)
    assert "Đã từ chối · AP-2" in markup
    assert "Thiếu 950M vốn lưu động" in markup
    assert "AP-2 rejected · APR-002-REJECT" in markup
    assert "NOT_RECOMMEND" in markup
    assert _button(app, "approve_ap4").disabled is True
    assert not any(item.key == "final_approve" for item in app.button)

    _button(app, "review_ap2").click().run()
    assert app.session_state["ap2_status"] == "pending"
    assert app.session_state["ap2_reject_reason"] == ""
    markup = "\n".join(item.value for item in app.markdown)
    assert "Chưa duyệt · AP-2" in markup


@pytest.mark.parametrize(
    ("button_key", "expected_state", "banner_title"),
    [
        ("final_reject", "REJECTED", "CON-004 đã bị từ chối"),
        (
            "final_need_info",
            "NEED_MORE_INFORMATION",
            "Founder yêu cầu bổ sung thông tin",
        ),
        (
            "final_renegotiate",
            "RENEGOTIATE",
            "Founder chọn đàm phán lại CON-004",
        ),
    ],
)
def test_non_active_final_states_have_banner_and_zone1_kpi(
    monkeypatch,
    button_key,
    expected_state,
    banner_title,
):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = _advance_to_ap4(_app())

    _button(app, button_key).click().run()

    assert app.session_state["final_state"] == expected_state
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert banner_title in markup
    assert "Trạng thái CON-004" in markup
    assert expected_state in markup
    assert not any(
        item.key
        in {
            "final_approve",
            "final_reject",
            "final_need_info",
            "final_renegotiate",
        }
        for item in app.button
    )


def test_non_primary_contract_keeps_precheck_transparency(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = _app()
    contract = next(item for item in app.selectbox if item.label == "Hợp đồng trọng tâm")
    contract.set_value("CON-001").run()
    app.radio[0].set_value("Chi tiết hợp đồng").run()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "Contract Precheck" in markup
    assert "CON-004 là case được kiểm chứng end-to-end" in "\n".join(
        item.value for item in app.info
    )


def test_openai_narrative_is_gated_cached_and_explicitly_regenerated(monkeypatch):
    calls = _install_openai_stub(monkeypatch)
    app = _app()

    # Initial render and ordinary navigation before AP-1 must not call GPT.
    assert calls["create"] == 0
    app.radio[0].set_value(app.radio[0].options[1]).run()
    assert calls["create"] == 0

    # The explicit two-agent analysis makes one cached Founder-insight call.
    _button(app, "analyze_con004").click().run()
    assert calls["create"] == 1
    assert app.session_state["zone2_founder_insight_cache"]["signature"]
    assert "OPENAI · LIVE" in "\n".join(item.value for item in app.markdown)

    # AP-1 unlocks exactly one additional Decision Card synthesis.
    _button(app, "approve_ap1").click().run()
    assert calls["create"] == 2
    assert app.session_state["openai_narrative_cache"]["signature"]
    assert "API CALL" in "\n".join(item.value for item in app.markdown)

    # Filters and later approvals reuse the narrative instead of calling GPT.
    app.selectbox[0].set_value(app.selectbox[0].options[1]).run()
    assert calls["create"] == 2
    assert "SESSION CACHE" in "\n".join(item.value for item in app.markdown)
    _button(app, "approve_ap2").click().run()
    assert calls["create"] == 2

    # A deliberate regeneration clears the cache and performs one new call.
    _button(app, "regenerate_openai_narrative").click().run()
    assert calls["create"] == 3

    # A changed input signature also invalidates the cached narrative.
    stale_cache = dict(app.session_state["openai_narrative_cache"])
    stale_cache["signature"] = "stale-input-signature"
    app.session_state["openai_narrative_cache"] = stale_cache
    app.selectbox[0].set_value(app.selectbox[0].options[0]).run()
    assert calls["create"] == 4
    assert not app.exception
