from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.resolvers import (
    build_cashflow_report,
    build_finance_output,
    derive_credit_assessments,
    evidence_missing,
    rank_open_invoices,
    resolve_execution_feasibility,
)
from src.team_pack import load_policy, load_team_pack, workbook_columns
from src.validation import (
    build_data_health_report,
    build_risk_output,
    validate_dictionary_columns,
)


ROOT = Path(__file__).parents[1]
WORKBOOK = ROOT / "data" / "MISTalent2026_OPC_AgenticAI_TeamPack_v2-1.xlsx"


@pytest.fixture(scope="session")
def team_pack():
    return load_team_pack(WORKBOOK)


@pytest.fixture(scope="session")
def policy():
    return load_policy(ROOT / "config" / "policies.yaml")


def _by_id(rows, key, value):
    return next(row for row in rows if row[key] == value)


def test_feasibility_joins_via_orders(team_pack, policy):
    contract = _by_id(team_pack["04_CONTRACTS"], "contract_id", "CON-004")

    result = resolve_execution_feasibility(
        contract, team_pack["06_ORDERS"], team_pack["05_PRODUCTS"], policy
    )

    assert result.service_ids == ["SVC-004"]
    assert result.matched_service_list_price_vnd == 4_200_000_000
    assert result.execution_feasible is True
    assert result.issues == []


def test_contract_without_orders_returns_none(team_pack, policy):
    contract = {
        "contract_id": "CON-NEW",
        "contract_value": 1_000_000_000,
    }

    result = resolve_execution_feasibility(
        contract, team_pack["06_ORDERS"], team_pack["05_PRODUCTS"], policy
    )

    assert result.execution_feasible is None
    assert result.issues[0].code == "CONTRACT_ORDERS_NOT_FOUND"


def test_worst_month_by_funding_need(team_pack, policy):
    report = build_cashflow_report(team_pack["09_CASHFLOW"], policy)

    assert report.worst_month == "2026-07"
    assert report.worst_month_basis == "funding_need"
    assert report.worst_month_funding_need_vnd == 1_190_000_000
    assert report.worst_month_reserve_gap_vnd == 680_000_000


def test_worst_month_policy_flip(team_pack, policy):
    reserve_policy = policy.model_copy(update={"worst_month_basis": "reserve_gap"})

    report = build_cashflow_report(team_pack["09_CASHFLOW"], reserve_policy)

    assert report.worst_month == "2026-06"
    assert report.worst_month_basis == "reserve_gap"
    assert report.worst_month_reserve_gap_vnd == 710_000_000
    assert report.worst_month_funding_need_vnd == 732_000_000


def test_both_gap_metrics_are_emitted(team_pack, policy):
    report = build_cashflow_report(team_pack["09_CASHFLOW"], policy)
    july = next(month for month in report.months if month.month == "2026-07")

    assert july.reserve_gap_vnd == 680_000_000
    assert july.funding_need_vnd == 1_190_000_000
    assert july.reserve_gap_basis
    assert july.funding_need_basis


def test_evidence_missing_only_cr003(team_pack, policy):
    actual = [
        evidence_missing(case["precheck_note"], policy.evidence_missing_markers)
        for case in team_pack["10_CREDIT_PROFILE"]
    ]

    assert actual == [False, False, True, False]


def test_cr001_evidence_word_is_not_blocking(team_pack, policy):
    case = _by_id(team_pack["10_CREDIT_PROFILE"], "credit_case_id", "CR-001")

    assert "evidence" in case["precheck_note"].casefold()
    assert not evidence_missing(case["precheck_note"], policy.evidence_missing_markers)


def test_priority_by_amount(team_pack):
    items, _, _ = rank_open_invoices(
        team_pack["07_INVOICES"], team_pack["03_CUSTOMERS"]
    )

    assert [item.invoice_id for item in items] == ["INV-004", "INV-002", "INV-003"]
    assert [item.priority_rank for item in items] == [1, 2, 3]


def test_high_risk_by_reliability(team_pack):
    items, high_risk, _ = rank_open_invoices(
        team_pack["07_INVOICES"], team_pack["03_CUSTOMERS"]
    )

    assert high_risk == "INV-002"
    assert next(item for item in items if item.invoice_id == "INV-002").risk_rank == 1


def test_unknown_customer_no_crash(team_pack):
    invoices = deepcopy(team_pack["07_INVOICES"])
    invoices.append(
        {
            "invoice_id": "INV-099",
            "order_id": "ORD-099",
            "customer_id": "CUS-099",
            "status": "Open",
            "invoice_amount": 999_000_000,
        }
    )

    items, high_risk, issues = rank_open_invoices(invoices, team_pack["03_CUSTOMERS"])
    unknown = next(item for item in items if item.invoice_id == "INV-099")

    assert unknown.priority_rank == 1
    assert unknown.risk_rank == len(items)
    assert unknown.payment_reliability is None
    assert high_risk == "INV-002"
    assert any(issue.code == "CUSTOMER_NOT_FOUND" for issue in issues)


def test_dt2_diverges_from_raw_approval_status(team_pack, policy):
    assessments = derive_credit_assessments(team_pack["10_CREDIT_PROFILE"], policy)
    cr003 = next(item for item in assessments if item.credit_case_id == "CR-003")

    assert cr003.derived_decision == "Hold — No recommendation"
    assert cr003.raw_approval_status == "Review"
    assert cr003.divergence_id == "DIV-001"


def test_validator_ignores_dictionary_sheet_names(team_pack):
    result = validate_dictionary_columns(
        team_pack["19_DATA_DICTIONARY"], workbook_columns(team_pack)
    )

    assert result.missing_columns == []
    assert result.issues == []
    assert result.excluded_columns == ["expected_reasoning"]
    assert "order_revenue" in result.matched_columns


def test_crosschecks_have_five_matches_and_one_visible_divergence(team_pack, policy):
    report = build_data_health_report(team_pack, policy)

    assert report.matched_count == 5
    assert report.divergence_count == 1
    assert next(check for check in report.checks if check.check_id == "DIV-001").status == (
        "divergence"
    )


def test_crosscheck_absence_is_not_a_contradiction(team_pack, policy):
    without_alert = deepcopy(team_pack)
    without_alert["14_ALERTS"] = [
        alert
        for alert in without_alert["14_ALERTS"]
        if alert["alert_type"] != "Missing document"
    ]

    report = build_data_health_report(without_alert, policy)
    check = next(item for item in report.checks if item.check_id == "CHK-EVIDENCE-MISSING")

    assert check.status == "not_checked"
    assert report.not_checked_count == 1


def test_finance_fixture_matches_team_pack(team_pack, policy):
    actual = build_finance_output(team_pack, policy, WORKBOOK.name).model_dump(mode="json")
    expected = json.loads((ROOT / "fixtures" / "finance_output_sample.json").read_text("utf-8"))

    assert actual == expected
    assert "gap_magnitude" not in json.dumps(actual)


def test_risk_fixture_matches_team_pack(team_pack, policy):
    actual = build_risk_output(team_pack, policy, WORKBOOK.name).model_dump(mode="json")
    expected = json.loads((ROOT / "fixtures" / "risk_output_sample.json").read_text("utf-8"))

    assert actual == expected
    assert "due_date × reliability" not in json.dumps(actual)
