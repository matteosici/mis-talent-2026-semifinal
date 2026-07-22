from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from src.agents import run_ds1_backend
from src.decision_agent import (
    PROTOTYPE_COLLATERAL_BASIS,
    SHEET_COLLATERAL_BASIS,
    _call_openai_for_narrative,
    _fallback_openai_result,
    _validate_narrative,
    build_decision_card,
    call_bank_api_mock,
    resolve_recommendation,
)
from src.runtime_log import build_sample_runtime_log
from src.team_pack import load_team_pack


ROOT = Path(__file__).parents[1]
WORKBOOK = ROOT / "data" / "MISTalent2026_OPC_AgenticAI_TeamPack_v2-1.xlsx"
POLICY = ROOT / "config" / "policies.yaml"


@pytest.fixture(scope="module")
def team_pack():
    return load_team_pack(WORKBOOK)


@pytest.fixture(scope="module")
def backend():
    return run_ds1_backend(WORKBOOK, POLICY)


@pytest.mark.parametrize(
    ("conflicts", "conditions", "rationale", "expected"),
    [
        ([{"description": "conflict"}], ["condition"], "rationale", True),
        ("not-a-list", ["condition"], "rationale", False),
        (["not-a-dict"], ["condition"], "rationale", False),
        ([], "not-a-list", "rationale", False),
        ([], [1], "rationale", False),
        ([], [], "   ", False),
        (None, None, None, False),
    ],
)
def test_validate_narrative(
    conflicts,
    conditions,
    rationale,
    expected: bool,
):
    assert _validate_narrative(conflicts, conditions, rationale) is expected


def _install_openai_stub(
    monkeypatch,
    *,
    output_text: str = "",
    error: Exception | None = None,
) -> dict[str, object]:
    calls: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            calls["create"] = kwargs
            if error:
                raise error
            return type(
                "FakeResponse",
                (),
                {"id": "resp-test", "output_text": output_text},
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.responses = FakeResponses()

    module = ModuleType("openai")
    module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return calls


def test_openai_live_path_strips_fence_validates_and_sets_params(
    backend,
    monkeypatch,
):
    payload = {
        "conflicts_detected": [{"description": "conflict"}],
        "conditions": ["condition"],
        "rationale": "rationale",
    }
    calls = _install_openai_stub(
        monkeypatch,
        output_text=f"```json\n{json.dumps(payload)}\n```",
    )

    result = _call_openai_for_narrative(backend, [])

    assert result.conflicts_detected == payload["conflicts_detected"]
    assert result.conditions == payload["conditions"]
    assert result.rationale == payload["rationale"]
    assert result.llm_meta["mode"] == "live"
    assert result.llm_meta["schema_validation"] == "PASSED"
    assert calls["client"] == {"timeout": 30}
    assert calls["create"]["temperature"] == 0  # type: ignore[index]
    assert calls["create"]["max_output_tokens"] == 1000  # type: ignore[index]


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "conflicts_detected": [],
            "conditions": "not-a-list",
            "rationale": "rationale",
        },
        {
            "conflicts_detected": [],
            "rationale": "missing conditions key",
        },
    ],
)
def test_openai_invalid_schema_falls_back_and_records_failure(
    backend,
    monkeypatch,
    invalid_payload,
):
    _install_openai_stub(
        monkeypatch,
        output_text=json.dumps(invalid_payload),
    )

    result = _call_openai_for_narrative(backend, [])

    assert result.conditions == _fallback_openai_result(backend).conditions
    assert result.llm_meta["mode"] == "fallback_after_invalid_schema"
    assert result.llm_meta["schema_validation"] == "FAILED"
    assert result.llm_meta["safe_failure_reason"] == "invalid_narrative_schema"


def test_openai_error_marks_schema_validation_not_run(backend, monkeypatch):
    _install_openai_stub(monkeypatch, error=RuntimeError("test failure"))

    result = _call_openai_for_narrative(backend, [])

    assert result.llm_meta["mode"] == "fallback_after_error"
    assert result.llm_meta["schema_validation"] == "NOT_RUN"
    assert result.llm_meta["safe_failure_reason"] == "RuntimeError"


@pytest.mark.parametrize(
    ("final_state", "pending", "missing", "expected"),
    [
        ("ACTIVE", True, True, "RECOMMEND"),
        ("REJECTED", False, False, "NOT_RECOMMEND"),
        ("RENEGOTIATE", False, False, "CONDITIONAL_RECOMMEND"),
        ("NEED_MORE_INFORMATION", False, False, "NEEDS_INFO"),
        ("DECISION_READY", False, True, "NOT_RECOMMEND"),
        ("DECISION_READY", True, False, "CONDITIONAL_RECOMMEND"),
        ("DECISION_READY", False, False, "RECOMMEND"),
    ],
)
def test_resolve_recommendation(
    final_state: str,
    pending: bool,
    missing: bool,
    expected: str,
):
    assert resolve_recommendation(final_state, pending, missing) == expected


def test_fallback_conditions_follow_backend_ids(backend):
    hold = backend.risk.d5_handoff.transaction_hold.model_copy(
        update={"txn_ids": ["TXN-DYNAMIC"]}
    )
    risk_handoff = backend.risk.d5_handoff.model_copy(
        update={"transaction_hold": hold}
    )
    risk_output = backend.risk.model_copy(update={"d5_handoff": risk_handoff})

    finance_handoff = backend.finance.d5_handoff.model_copy(
        update={"credit_candidate_ids": ["CR-004"]}
    )
    credit_plan = backend.finance.credit_plan.model_copy(
        update={"decision_package_credit_case_ids": ["CR-004"]}
    )
    finance_output = backend.finance.model_copy(
        update={"d5_handoff": finance_handoff, "credit_plan": credit_plan}
    )
    changed = backend.model_copy(
        update={"finance": finance_output, "risk": risk_output}
    )

    result = _fallback_openai_result(changed)
    conditions = "\n".join(result.conditions)

    assert result.llm_meta["schema_validation"] == "PASSED"
    assert "TXN-DYNAMIC" in conditions
    assert "TXN-006/TXN-007" not in conditions
    assert "CR-004" in conditions
    assert "CR-001" not in conditions


def test_decision_card_uses_runtime_transaction_hold_ids(backend, team_pack):
    hold = backend.risk.d5_handoff.transaction_hold.model_copy(
        update={"txn_ids": ["TXN-DYNAMIC-1", "TXN-DYNAMIC-2"]}
    )
    risk_handoff = backend.risk.d5_handoff.model_copy(
        update={"transaction_hold": hold}
    )
    risk_output = backend.risk.model_copy(update={"d5_handoff": risk_handoff})
    changed = backend.model_copy(update={"risk": risk_output})

    card = build_decision_card(changed, team_pack, use_openai=False)
    ap1 = next(item for item in card["approval_required"] if item["id"] == "AP-1")

    assert ap1["description"] == "Tạm giữ TXN-DYNAMIC-1/TXN-DYNAMIC-2"
    assert card["critical_flags"] == [
        "TXN-DYNAMIC-1/TXN-DYNAMIC-2 chưa được xác nhận tạm giữ"
    ]
    assert "TXN-006/007" not in ap1["description"]


def test_runtime_log_defaults_schema_validation_to_not_run():
    events = build_sample_runtime_log({"llm_meta": {}})
    source_event = next(
        item for item in events if item["tool_or_api_id"] == "TEAM_PACK_EXCEL"
    )
    schema_event = next(
        item for item in events if item["tool_or_api_id"] == "SCHEMA_VALIDATION"
    )

    assert source_event["response_status"] == (
        "14_sheets_loaded_8_core_6_supporting"
    )
    assert schema_event["response_status"] == "NOT_RUN"


def test_build_decision_card_syncs_approval_status_and_final_state(
    backend,
    team_pack,
):
    card = build_decision_card(
        backend,
        team_pack,
        use_openai=False,
        ap1_status="approved",
        ap2_status="approved",
        ap3_status="approved",
        ap4_status="approved",
        final_state="ACTIVE",
    )
    statuses = {item["id"]: item["status"] for item in card["approval_required"]}
    blocks = {item["id"]: item["blocks"] for item in card["approval_required"]}

    assert statuses == {
        "AP-1": "approved",
        "AP-2": "approved",
        "AP-3": "approved",
        "AP-4": "approved",
        "AP-5": "approved",
    }
    assert blocks["AP-2"] == ["AP-4", "AP-5"]
    assert blocks["AP-3"] == ["AP-4", "AP-5"]
    assert card["recommendation"] == "RECOMMEND"


def test_build_decision_card_rejected_overrides_pending_evidence(
    backend,
    team_pack,
):
    card = build_decision_card(
        backend,
        team_pack,
        use_openai=False,
        final_state="REJECTED",
    )

    assert card["recommendation"] == "NOT_RECOMMEND"


def test_collateral_is_marked_as_prototype_fallback(backend, team_pack):
    card = build_decision_card(backend, team_pack, use_openai=False)

    assert card["financial_ask"]["collateral_total"] == 226_500_000
    assert card["financial_ask"]["collateral_total_basis"] == (
        PROTOTYPE_COLLATERAL_BASIS
    )
    assert all(
        row["collateral_basis"] == PROTOTYPE_COLLATERAL_BASIS
        for row in card["bank_fit_matrix"]
    )


def test_collateral_prefers_absolute_values_from_bank_product_sheet(
    backend,
    team_pack,
):
    collateral_by_product = {
        "BANKPROD-002": 83_000_000,
        "BANKPROD-003": 0,
        "BANKPROD-004": 141_000_000,
        "BANKPROD-006": 21_000_000,
    }
    changed_products = [dict(row) for row in team_pack["11_BANK_PRODUCTS"]]
    for product in changed_products:
        product_id = str(product["bank_product_id"])
        if product_id in collateral_by_product:
            product["collateral_vnd"] = collateral_by_product[product_id]
    changed_team_pack = {
        **team_pack,
        "11_BANK_PRODUCTS": changed_products,
    }

    card = build_decision_card(backend, changed_team_pack, use_openai=False)
    rows = {
        row["bank_product_id"]: row for row in card["bank_fit_matrix"]
    }

    for product_id, expected in collateral_by_product.items():
        assert rows[product_id]["collateral_vnd"] == expected
        assert rows[product_id]["collateral_basis"] == SHEET_COLLATERAL_BASIS
        assert rows[product_id]["demo_note"].startswith("Read from")
    assert card["financial_ask"]["collateral_total"] == 224_000_000
    assert card["financial_ask"]["collateral_total_basis"] == (
        SHEET_COLLATERAL_BASIS
    )


@pytest.mark.parametrize("status", [400, 401, 409, 429, 503])
def test_bank_api_mock_exposes_safe_failure(status, team_pack):
    result = call_bank_api_mock(
        "CR-002",
        420_000_000,
        status,
        api_catalog=team_pack["12_API_CATALOG"],
        sandbox_contracts=team_pack["22_SANDBOX_CONTRACT"],
    )

    assert result["api_id"] == "API-002"
    assert result["submitted_to_real_bank"] is False
    assert result["ok"] is False
    assert result["error_code"]
    assert result["required_handling"]
    assert result["contract_status_supported"] is (status != 429)


def test_bank_api_mock_reads_catalog_and_contract(team_pack):
    result = call_bank_api_mock(
        "CR-002",
        420_000_000,
        200,
        api_catalog=team_pack["12_API_CATALOG"],
        sandbox_contracts=team_pack["22_SANDBOX_CONTRACT"],
    )

    assert result["ok"] is True
    assert result["endpoint"] == "/openapi/v1/guarantee/precheck"
    assert result["requires_human_approval"] == "Yes before submission"


def test_bank_api_mock_unknown_case_fails_closed(team_pack):
    result = call_bank_api_mock(
        "CR-UNKNOWN",
        100_000_000,
        api_catalog=team_pack["12_API_CATALOG"],
        sandbox_contracts=team_pack["22_SANDBOX_CONTRACT"],
    )

    assert result["ok"] is False
    assert result["api_id"] is None
    assert result["error_code"] == "credit_api_mapping_not_found"


def test_bank_api_mock_invalid_status_fails_closed(team_pack):
    result = call_bank_api_mock(
        "CR-002",
        420_000_000,
        "not-a-status",  # type: ignore[arg-type]
        api_catalog=team_pack["12_API_CATALOG"],
        sandbox_contracts=team_pack["22_SANDBOX_CONTRACT"],
    )

    assert result["ok"] is False
    assert result["http_status"] == 400
    assert result["error_code"] == "validation_error"
