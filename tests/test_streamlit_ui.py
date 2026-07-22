from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

from streamlit.testing.v1 import AppTest


APP = Path(__file__).parents[1] / "app.py"


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=60).run()


def _button(app: AppTest, key: str):
    return next(item for item in app.button if item.key == key)


def _install_openai_stub(monkeypatch) -> dict[str, int]:
    calls = {"create": 0}
    payload = {
        "conflicts_detected": [
            {
                "description": "conflict",
                "resolution_note": "resolution",
            }
        ],
        "conditions": ["condition"],
        "rationale": "rationale",
    }

    class FakeResponses:
        def create(self, **kwargs):
            calls["create"] += 1
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

    period = next(item for item in app.selectbox if item.label == "Kỳ phân tích")
    period.set_value("Quý hiện tại").run()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "3/3 tháng" in markup


def test_contract_detail_starts_collapsed_and_approval_gates_work(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
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

    # AP-1 unlocks exactly one live synthesis.
    _button(app, "approve_ap1").click().run()
    assert calls["create"] == 1
    assert app.session_state["openai_narrative_cache"]["signature"]
    assert "API CALL" in "\n".join(item.value for item in app.markdown)

    # Filters and later approvals reuse the narrative instead of calling GPT.
    app.selectbox[0].set_value(app.selectbox[0].options[1]).run()
    assert calls["create"] == 1
    assert "SESSION CACHE" in "\n".join(item.value for item in app.markdown)
    _button(app, "approve_ap2").click().run()
    assert calls["create"] == 1

    # A deliberate regeneration clears the cache and performs one new call.
    _button(app, "regenerate_openai_narrative").click().run()
    assert calls["create"] == 2

    # A changed input signature also invalidates the cached narrative.
    stale_cache = dict(app.session_state["openai_narrative_cache"])
    stale_cache["signature"] = "stale-input-signature"
    app.session_state["openai_narrative_cache"] = stale_cache
    app.selectbox[0].set_value(app.selectbox[0].options[0]).run()
    assert calls["create"] == 3
    assert not app.exception
