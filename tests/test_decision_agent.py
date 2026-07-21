from __future__ import annotations

from pathlib import Path

import pytest

from src.agents import run_ds1_backend
from src.decision_agent import (
    PROTOTYPE_COLLATERAL_BASIS,
    _fallback_openai_result,
    build_decision_card,
    call_bank_api_mock,
    resolve_recommendation,
)
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

    assert "TXN-DYNAMIC" in conditions
    assert "TXN-006/TXN-007" not in conditions
    assert "CR-004" in conditions
    assert "CR-001" not in conditions


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

    assert statuses == {
        "AP-1": "approved",
        "AP-2": "approved",
        "AP-3": "approved",
        "AP-4": "approved",
        "AP-5": "approved",
    }
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

    assert card["financial_ask"]["collateral_total_basis"] == (
        PROTOTYPE_COLLATERAL_BASIS
    )
    assert all(
        row["collateral_basis"] == PROTOTYPE_COLLATERAL_BASIS
        for row in card["bank_fit_matrix"]
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
