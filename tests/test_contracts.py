from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.agents import run_ds1_backend
from src.resolvers import (
    build_cashflow_report,
    build_finance_output,
    customer_intake,
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

# Golden figures below come from NhiemVuHeThong_Report.pdf, especially
# D5 sections 5.1/5.2 (pages 8-10) and appendices 4.3/5.1 (pages 19-21).


@pytest.fixture(scope="session")
def team_pack():
    return load_team_pack(WORKBOOK)


@pytest.fixture(scope="session")
def policy():
    return load_policy(ROOT / "config" / "policies.yaml")


@pytest.fixture(scope="session")
def finance_output(team_pack, policy):
    return build_finance_output(team_pack, policy, WORKBOOK.name)


@pytest.fixture(scope="session")
def risk_output(team_pack, policy):
    return build_risk_output(team_pack, policy, WORKBOOK.name)


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


def test_customer_intake_verifies_con004_with_real_reliability(team_pack):
    contract = _by_id(team_pack["04_CONTRACTS"], "contract_id", "CON-004")

    status, issues = customer_intake(contract, team_pack["03_CUSTOMERS"])

    assert status.contract_id == "CON-004"
    assert status.customer_id == "CUS-005"
    assert status.verified is True
    assert status.flag is None
    assert status.payment_reliability == 0.83
    assert status.basis == "customer_id existence in 03_CUSTOMERS"
    assert issues == []


def test_customer_intake_unknown_customer_surfaces_gate_without_crash(
    team_pack, policy
):
    changed = deepcopy(team_pack)
    contract = _by_id(changed["04_CONTRACTS"], "contract_id", "CON-004")
    contract["customer_id"] = "CUS-099"

    output = build_finance_output(changed, policy, WORKBOOK.name)
    status = next(item for item in output.intake if item.contract_id == "CON-004")

    assert status.customer_id == "CUS-099"
    assert status.verified is False
    assert status.flag == "unverified"
    assert status.payment_reliability is None
    assert output.d5_handoff.customer_verified is False
    assert any(
        issue.code == "CUSTOMER_UNVERIFIED" and issue.record_id == "CUS-099"
        for issue in output.issues
    )


def test_customer_intake_missing_customer_id_has_distinct_issue(team_pack, policy):
    changed = deepcopy(team_pack)
    contract = _by_id(changed["04_CONTRACTS"], "contract_id", "CON-004")
    contract["customer_id"] = None

    output = build_finance_output(changed, policy, WORKBOOK.name)
    status = next(item for item in output.intake if item.contract_id == "CON-004")

    assert status.customer_id == ""
    assert status.verified is False
    assert status.flag == "customer_id_missing"
    assert status.payment_reliability is None
    assert output.d5_handoff.customer_verified is False
    assert any(
        issue.code == "CUSTOMER_ID_MISSING" and issue.record_id == "CON-004"
        for issue in output.issues
    )


def test_finance_surfaces_new_opportunity_feasibility(team_pack, policy):
    output = build_finance_output(team_pack, policy, WORKBOOK.name)
    feasibility = {item.contract_id: item for item in output.feasibility}

    assert set(feasibility) == {"CON-004", "CON-005"}
    assert feasibility["CON-004"].execution_feasible is True
    assert output.d5_handoff.execution_feasible is True


def test_finance_unknown_service_surfaces_unknown_gate(team_pack, policy):
    changed = deepcopy(team_pack)
    for order in changed["06_ORDERS"]:
        if order.get("contract_id") == "CON-004":
            order["service_id"] = "SVC-999"

    output = build_finance_output(changed, policy, WORKBOOK.name)
    feasibility = next(
        item for item in output.feasibility if item.contract_id == "CON-004"
    )

    assert feasibility.execution_feasible is None
    assert feasibility.issues[0].code == "SERVICE_NOT_FOUND"
    assert output.d5_handoff.execution_feasible is None
    assert any(issue.code == "SERVICE_NOT_FOUND" for issue in output.issues)


def test_finance_value_mismatch_surfaces_false_gate(team_pack, policy):
    changed = deepcopy(team_pack)
    contract = _by_id(changed["04_CONTRACTS"], "contract_id", "CON-004")
    contract["contract_value"] += 1

    output = build_finance_output(changed, policy, WORKBOOK.name)
    feasibility = next(
        item for item in output.feasibility if item.contract_id == "CON-004"
    )

    assert feasibility.execution_feasible is False
    assert feasibility.issues[0].code == "SERVICE_VALUE_MISMATCH"
    assert output.d5_handoff.execution_feasible is False
    assert any(issue.code == "SERVICE_VALUE_MISMATCH" for issue in output.issues)


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


def test_cashflow_severity_matches_report(team_pack, policy):
    report = build_cashflow_report(team_pack["09_CASHFLOW"], policy)

    assert [month.severity for month in report.months] == [
        "Critical",
        "Critical",
        "Critical",
        "High",
        "High",
        "High",
    ]


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


def test_ds1_ingestion_audit_reads_all_required_sources(finance_output):
    audit = finance_output.source_audit

    assert audit is not None
    assert audit.core_complete is True
    assert audit.missing_sheets == []
    assert audit.row_counts["04_CONTRACTS"] == 5
    assert audit.row_counts["09_CASHFLOW"] == 6
    assert audit.row_counts["07_INVOICES"] == 7
    assert audit.row_counts["08_BANK_TXN"] == 10
    assert audit.row_counts["13_RISK_RULES"] == 7
    assert audit.row_counts["14_ALERTS"] == 5
    assert audit.row_counts["10_CREDIT_PROFILE"] == 4
    assert audit.row_counts["11_BANK_PRODUCTS"] == 8


def test_excel_dates_are_normalized(team_pack):
    txn006 = _by_id(team_pack["08_BANK_TXN"], "txn_id", "TXN-006")

    assert txn006["txn_date"].startswith("2026-")


def test_receivable_aging_matches_d5(finance_output):
    report = finance_output.receivable_aging

    assert report is not None
    assert report.open_invoices_total_vnd == 635_000_000
    assert report.not_issued_invoices_total_vnd == 2_760_000_000
    assert report.high_risk_invoice_id == "INV-002"
    assert report.critical_dependency_invoice_id == "INV-005"
    assert report.critical_dependency_contract_id == "CON-004"


def test_margin_warnings_and_gross_profit_match_report(finance_output):
    warnings = [item.contract_id for item in finance_output.margin_analysis if item.warning]
    con004 = next(
        item for item in finance_output.margin_analysis if item.contract_id == "CON-004"
    )

    assert warnings == ["CON-002", "CON-004"]
    assert con004.gross_profit_vnd == 1_008_000_000


def test_rr003_sheet_threshold_drives_margin(team_pack, policy):
    changed = deepcopy(team_pack)
    rr003 = _by_id(changed["13_RISK_RULES"], "rule_id", "RR-003")
    rr003["trigger_condition"] = "gross_margin < 0.25"

    output = build_finance_output(changed, policy, WORKBOOK.name)

    assert [item.contract_id for item in output.margin_analysis if item.warning] == ["CON-004"]
    assert any(issue.code == "MARGIN_THRESHOLD_DIVERGENCE" for issue in output.issues)


def test_credit_candidates_and_bridge_match_report(finance_output):
    active = [
        item.credit_case_id
        for item in finance_output.credit_candidates
        if item.candidate_status != "hold"
    ]
    cr002 = next(
        item for item in finance_output.credit_candidates if item.credit_case_id == "CR-002"
    )
    plan = finance_output.credit_plan

    assert active == ["CR-004", "CR-001", "CR-002"]
    assert cr002.candidate_status == "borderline"
    assert plan.priority_bridge_credit_case_ids == ["CR-004", "CR-001"]
    assert plan.priority_bridge_amount_vnd == 1_170_000_000
    assert plan.priority_bridge_shortfall_vnd == 20_000_000
    assert plan.decision_package_credit_case_ids == ["CR-001", "CR-002"]
    assert plan.decision_package_total_ask_vnd == 1_370_000_000
    assert plan.held_credit_case_ids == ["CR-003"]


def test_rr001_scan_and_cluster_match_report(risk_output):
    assert [item.txn_id for item in risk_output.transaction_findings] == [
        "TXN-006",
        "TXN-007",
    ]
    cluster = risk_output.transaction_clusters[0]
    assert cluster.criteria_match_count == 3
    assert cluster.matched_criteria == [
        "same_counterparty",
        "same_day",
        "same_pattern",
    ]
    assert cluster.total_exposure_vnd == 178_000_000
    assert cluster.alert_id == "AL-001"
    assert cluster.alert_consistent is True
    assert cluster.hold_payload.action == "temporary_hold"
    assert risk_output.financial_flow_paused is True


def test_rr001_sheet_threshold_drives_scan(team_pack, policy):
    changed = deepcopy(team_pack)
    rr001 = _by_id(changed["13_RISK_RULES"], "rule_id", "RR-001")
    rr001["trigger_condition"] = "transaction_risk_score >= 95"

    output = build_risk_output(changed, policy, WORKBOOK.name)

    assert output.rule_snapshot.transaction_risk_threshold == 95
    assert output.transaction_findings == []
    assert output.transaction_clusters == []
    assert output.financial_flow_paused is False
    check = next(
        item
        for item in output.data_health.checks
        if item.check_id == "CHK-TRANSACTION-CLUSTER"
    )
    assert check.status == "divergence"


def test_missing_rr001_uses_explicit_policy_fallback(team_pack, policy):
    changed = deepcopy(team_pack)
    changed["13_RISK_RULES"] = [
        row for row in changed["13_RISK_RULES"] if row["rule_id"] != "RR-001"
    ]

    output = build_risk_output(changed, policy, WORKBOOK.name)

    rr001 = next(
        rule for rule in output.rule_snapshot.applied_rules if rule.rule_id == "RR-001"
    )
    assert rr001.source == "policy_fallback"
    assert rr001.threshold == policy.transaction_risk_threshold == 85
    assert any(
        issue.code == "RISK_RULE_FALLBACK" and issue.record_id == "RR-001"
        for issue in output.issues
    )


def test_governance_and_credit_risk_flags_match_d5(risk_output):
    assert [item.record_id for item in risk_output.governance_flags] == [
        "CR-001",
        "CR-002",
        "CR-003",
    ]
    assert [item.credit_case_id for item in risk_output.credit_risk_flags] == [
        "CR-002",
        "CR-003",
    ]
    cr002 = next(
        item for item in risk_output.credit_risk_flags if item.credit_case_id == "CR-002"
    )
    cr003 = next(
        item for item in risk_output.credit_risk_flags if item.credit_case_id == "CR-003"
    )
    assert cr002.disposition == "borderline"
    assert cr003.disposition == "hold"


def test_execution_risk_penalty_matches_report(risk_output):
    assert [item.order_id for item in risk_output.execution_risks] == [
        "ORD-004",
        "ORD-008",
    ]
    ord004 = next(item for item in risk_output.execution_risks if item.order_id == "ORD-004")
    ord008 = next(item for item in risk_output.execution_risks if item.order_id == "ORD-008")
    assert ord004.systemic is True
    assert ord004.late_delivery_days_threshold == 7
    assert ord004.potential_penalty_vnd_per_day == 4_650_000
    assert ord008.systemic is True
    assert ord008.late_delivery_days_threshold == 7
    assert ord008.potential_penalty_vnd_per_day == 6_300_000


def test_safe_handling_uses_published_masking_examples(risk_output):
    notes = {item.field_name: item for item in risk_output.safe_handling_notes}

    assert notes["customer_id"].tokenized_value == "TOK-CUS-A91F"
    assert notes["account_id"].tokenized_value == "TOK-ACC-7D20"
    assert notes["contract_value"].masked_value == "4.2B band"
    assert notes["access_token"].masked_value == "[SECRET]"
    assert notes["access_token"].tokenized_value == "vault://sandbox/token"
    findings_serialized = json.dumps(
        [item.model_dump(mode="json") for item in risk_output.transaction_findings]
    )
    assert "OPC_MAIN" not in findings_serialized
    assert "UNK-ECOM" not in findings_serialized

    full_output = json.dumps(risk_output.model_dump(mode="json"))
    for raw_restricted_value in ("CUS-005", "OPC_MAIN", "UNK-ECOM", "eyJ...mock"):
        assert raw_restricted_value not in full_output


def test_d1_step3_and_step4_entrypoint_runs_real_backend():
    output = run_ds1_backend(WORKBOOK, ROOT / "config" / "policies.yaml")

    assert output.finance.d5_handoff.worst_month == "2026-07"
    assert output.finance.d5_handoff.credit_candidate_ids == [
        "CR-004",
        "CR-001",
        "CR-002",
    ]
    assert output.risk.d5_handoff.transaction_hold_amount_vnd == 178_000_000
    assert output.risk.d5_handoff.financial_flow_paused is True


def test_finance_fixture_matches_team_pack(finance_output):
    actual = finance_output.model_dump(mode="json")
    expected = json.loads((ROOT / "fixtures" / "finance_output_sample.json").read_text("utf-8"))

    assert actual == expected
    assert "gap_magnitude" not in json.dumps(actual)


def test_risk_fixture_matches_team_pack(risk_output):
    actual = risk_output.model_dump(mode="json")
    expected = json.loads((ROOT / "fixtures" / "risk_output_sample.json").read_text("utf-8"))

    assert actual == expected
    assert "due_date × reliability" not in json.dumps(actual)
