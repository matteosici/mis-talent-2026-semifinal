from __future__ import annotations

import json
import sys
from types import ModuleType

from src.founder_insights import (
    build_founder_insights,
    founder_insight_signature,
)


def _facts() -> dict:
    return {
        "transaction_ids": ["TXN-006", "TXN-007"],
        "transaction_count": 2,
        "transaction_amount_vnd": 178_000_000,
        "worst_month": "2026-07",
        "worst_month_funding_need_vnd": 1_190_000_000,
        "con004_gross_margin": 0.24,
        "margin_target": 0.28,
        "ord004_penalty_vnd_per_day": 4_650_000,
        "ord004_late_days_threshold": 7,
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


def _valid_live_payload() -> dict[str, str]:
    return {
        "blocker_situation": "TXN-006 và TXN-007 tạo rủi ro trực tiếp cho CON-004.",
        "blocker_action": "Founder cần xử lý AP-1 trước bước tiếp theo của CON-004.",
        "finance_funding": "CON-004 cần bổ sung vốn trước tháng căng nhất.",
        "finance_margin": "CON-004 cần rà lại giá và chi phí.",
        "finance_credit": "Ưu tiên CR-004, CR-001; bổ sung CR-002 và giữ CR-003.",
        "risk_transaction": "TXN-006 và TXN-007 đã được chặn.",
        "risk_order": "ORD-004 của CON-003 cần can thiệp để tránh phạt.",
        "risk_credit": "CR-003 của CON-005 cần xác nhận nhà cung cấp.",
    }


def _install_stub(monkeypatch, payload: dict[str, str], calls: list[dict]) -> None:
    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return type(
                "FakeResponse",
                (),
                {"id": "resp-founder-1", "output_text": json.dumps(payload)},
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    module = ModuleType("openai")
    module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4")


def test_fallback_is_actionable_and_deterministic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    facts = _facts()
    result = build_founder_insights(facts)

    assert result["llm_meta"]["mode"] == "fallback"
    assert "178 triệu VND" in result["blocker_situation"]
    assert "AP-1" in result["blocker_action"]
    assert "1,19 tỷ VND" in result["finance_funding"]
    assert "24%" in result["finance_margin"]
    assert "4,65 triệu VND/ngày" in result["risk_order"]
    assert founder_insight_signature(facts, "gpt-5.4") == founder_insight_signature(
        facts, "gpt-5.4"
    )


def test_live_response_uses_strict_schema(monkeypatch):
    calls: list[dict] = []
    _install_stub(monkeypatch, _valid_live_payload(), calls)

    result = build_founder_insights(_facts())

    assert result["llm_meta"]["mode"] == "live"
    assert result["llm_meta"]["schema_validation"] == "PASSED"
    assert result["llm_meta"]["response_id"] == "resp-founder-1"
    assert len(calls) == 1
    request = calls[0]
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert request["text"]["format"]["name"] == "founder_business_insights"
    assert request["temperature"] == 0


def test_missing_required_business_id_falls_back_safely(monkeypatch):
    calls: list[dict] = []
    invalid = _valid_live_payload()
    invalid["risk_credit"] = "Cần xác nhận nhà cung cấp trước khi xem xét lại."
    _install_stub(monkeypatch, invalid, calls)

    result = build_founder_insights(_facts())

    assert result["llm_meta"]["mode"] == "fallback_after_invalid_schema"
    assert result["llm_meta"]["schema_validation"] == "FAILED"
    assert result["llm_meta"]["safe_failure_reason"] == "invalid_founder_insight_schema"
    assert "CR-003" in result["risk_credit"]
    assert "CON-005" in result["risk_credit"]
