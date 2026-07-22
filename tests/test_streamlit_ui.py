from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).parents[1] / "app.py"


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=60).run()


def _button(app: AppTest, key: str):
    return next(item for item in app.button if item.key == key)


def test_overview_filters_render_without_exposing_raw_code(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = _app()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "Tổng số sheet đã đọc" in markup
    assert "Data Health &amp; Business Snapshot" in markup

    period = next(item for item in app.selectbox if item.label == "Kỳ phân tích")
    period.set_value("Quý hiện tại").run()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "3/3 tháng" in markup


def test_contract_detail_starts_collapsed_and_approval_gates_work(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = _app()
    app.radio[0].set_value("Chi tiết hợp đồng").run()
    assert not app.exception
    assert "Dữ liệu hợp đồng đã token hóa" in [item.label for item in app.expander]
    assert _button(app, "approve_ap1").disabled is False
    assert not any(item.key in {"approve_ap2", "approve_ap3", "approve_ap4"} for item in app.button)
    assert not any(item.key == "final_approve" for item in app.button)

    _button(app, "approve_ap1").click().run()
    assert app.session_state["ap1_status"] == "approved"
    assert app.session_state["final_state"] == "CREDIT_PACKAGE_PROPOSED"
    assert _button(app, "approve_ap2").disabled is False
    assert _button(app, "approve_ap3").disabled is False
    assert _button(app, "approve_ap4").disabled is True

    _button(app, "approve_ap2").click().run()
    _button(app, "approve_ap3").click().run()
    assert _button(app, "approve_ap4").disabled is False
    _button(app, "approve_ap4").click().run()
    assert app.session_state["ap4_status"] == "approved"
    assert app.session_state["final_state"] == "DECISION_READY"
    assert _button(app, "final_approve").disabled is False

    _button(app, "call_bank_api").click().run()
    assert app.session_state["bank_api_response"]["ok"] is True
    assert not app.exception

    _button(app, "final_approve").click().run()
    assert app.session_state["final_state"] == "ACTIVE"
    assert app.session_state["human_approval_id"] == "APR-FINAL-APPROVE"
    assert not app.exception


def test_non_primary_contract_keeps_precheck_transparency(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
