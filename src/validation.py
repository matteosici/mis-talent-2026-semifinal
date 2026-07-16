"""Cross-source checks that preserve mismatches instead of hiding them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    DataHealthCheck,
    DataHealthReport,
    DictionaryValidationResult,
    PolicyConfig,
    RiskOutput,
    ValidationIssue,
)
from .resolvers import (
    build_cashflow_report,
    derive_credit_assessments,
    evidence_missing,
    rank_open_invoices,
    resolve_execution_feasibility,
)


Record = Mapping[str, Any]


def validate_dictionary_columns(
    dictionary_rows: Sequence[Record],
    actual_columns: set[str],
    excluded_columns: set[str] | None = None,
) -> DictionaryValidationResult:
    """Validate by column name only; dictionary sheet numbers are known to be stale."""

    excluded = excluded_columns or {"expected_reasoning"}
    declared = {str(row["column_name"]) for row in dictionary_rows}
    matched = sorted((declared - excluded) & actual_columns)
    missing = sorted((declared - excluded) - actual_columns)
    issues = [
        ValidationIssue(
            code="DICTIONARY_COLUMN_NOT_FOUND",
            record_id=column,
            field="column_name",
            message=f"Declared column {column!r} is not present in the published workbook.",
        )
        for column in missing
    ]
    return DictionaryValidationResult(
        matched_columns=matched,
        missing_columns=missing,
        excluded_columns=sorted(declared & excluded),
        issues=issues,
    )


def _alert_by_type(alerts: Sequence[Record], alert_type: str) -> Record | None:
    return next(
        (
            alert
            for alert in alerts
            if str(alert.get("alert_type", "")).casefold() == alert_type.casefold()
        ),
        None,
    )


def _find(rows: Sequence[Record], key: str, value: str) -> Record | None:
    return next((row for row in rows if str(row.get(key, "")) == value), None)


def _not_checked(
    check_id: str,
    subject_id: str,
    source: str,
    message: str,
    derived_value: Any = None,
) -> DataHealthCheck:
    return DataHealthCheck(
        check_id=check_id,
        subject_id=subject_id,
        status="not_checked",
        derived_value=derived_value,
        reference_value=None,
        source=source,
        message=message,
    )


def build_data_health_report(
    team_pack: Mapping[str, Sequence[Record]], policy: PolicyConfig
) -> DataHealthReport:
    alerts = team_pack.get("14_ALERTS", [])
    credit_cases = team_pack.get("10_CREDIT_PROFILE", [])
    checks: list[DataHealthCheck] = []

    missing_alert = _alert_by_type(alerts, "Missing document")
    missing_case_id = str(missing_alert["related_record"]) if missing_alert else "CR-003"
    missing_case = _find(credit_cases, "credit_case_id", missing_case_id)
    if missing_alert is None or missing_case is None:
        checks.append(
            _not_checked(
                "CHK-EVIDENCE-MISSING",
                missing_case_id,
                "10_CREDIT_PROFILE ↔ 14_ALERTS",
                "Cross-check skipped because the case or independent alert is absent.",
            )
        )
    else:
        missing_derived = evidence_missing(
            missing_case.get("precheck_note"), policy.evidence_missing_markers
        )
        checks.append(
            DataHealthCheck(
                check_id="CHK-EVIDENCE-MISSING",
                subject_id=missing_case_id,
                status="matched" if missing_derived else "divergence",
                derived_value=missing_derived,
                reference_value=True,
                source="10_CREDIT_PROFILE ↔ 14_ALERTS",
                message="Blocking precheck note agrees with the independent missing-document alert.",
            )
        )

    margin_alert = _alert_by_type(alerts, "Margin pressure")
    margin_order_id = str(margin_alert["related_record"]) if margin_alert else ""
    margin_order = _find(team_pack.get("06_ORDERS", []), "order_id", margin_order_id)
    margin_contract = (
        _find(
            team_pack.get("04_CONTRACTS", []),
            "contract_id",
            str(margin_order.get("contract_id", "")),
        )
        if margin_order
        else None
    )
    if margin_alert is None or margin_order is None or margin_contract is None:
        checks.append(
            _not_checked(
                "CHK-MARGIN",
                margin_order_id or "unknown",
                "04_CONTRACTS ↔ 06_ORDERS ↔ 14_ALERTS",
                "Cross-check skipped because the alert, order or contract is absent.",
            )
        )
    else:
        margin_warning = float(margin_contract["gross_margin"]) < 0.28
        checks.append(
            DataHealthCheck(
                check_id="CHK-MARGIN",
                subject_id=str(margin_contract["contract_id"]),
                status="matched" if margin_warning else "divergence",
                derived_value=margin_warning,
                reference_value=True,
                source="04_CONTRACTS ↔ 06_ORDERS ↔ 14_ALERTS",
                message="Contract margin below target agrees with the order-level margin alert.",
            )
        )

    cash_alert = _alert_by_type(alerts, "Cashflow shortage")
    alert_month = str(cash_alert["related_record"]) if cash_alert else ""
    cashflow_rows = team_pack.get("09_CASHFLOW", [])
    if cash_alert is None or not cashflow_rows:
        checks.append(
            _not_checked(
                "CHK-CASHFLOW",
                alert_month or "unknown",
                "09_CASHFLOW ↔ 14_ALERTS",
                "Cross-check skipped because the cashflow rows or alert are absent.",
            )
        )
    else:
        cashflow = build_cashflow_report(cashflow_rows, policy)
        alert_cashflow = next(
            (month for month in cashflow.months if month.month == alert_month), None
        )
        if alert_cashflow is None:
            checks.append(
                _not_checked(
                    "CHK-CASHFLOW",
                    alert_month,
                    "09_CASHFLOW ↔ 14_ALERTS",
                    "Cross-check skipped because the alert month is absent from cashflow.",
                )
            )
        else:
            checks.append(
                DataHealthCheck(
                    check_id="CHK-CASHFLOW",
                    subject_id=alert_month,
                    status="matched" if alert_cashflow.breach else "divergence",
                    derived_value=alert_cashflow.breach,
                    reference_value=True,
                    source="09_CASHFLOW ↔ 14_ALERTS",
                    message="Derived reserve breach agrees with the cashflow-shortage alert.",
                )
            )

    txn_alert = _alert_by_type(alerts, "Transaction anomaly")
    derived_txn_ids = sorted(
        str(txn["txn_id"])
        for txn in team_pack.get("08_BANK_TXN", [])
        if float(txn["transaction_risk_score"]) >= 85
    )
    referenced_txn_ids = sorted(
        part.strip()
        for part in str(txn_alert["related_record"] if txn_alert else "").split(",")
        if part.strip()
    )
    if txn_alert is None:
        checks.append(
            _not_checked(
                "CHK-TRANSACTION-CLUSTER",
                ", ".join(derived_txn_ids) or "unknown",
                "08_BANK_TXN ↔ 14_ALERTS",
                "Cross-check skipped because the independent alert is absent.",
                derived_txn_ids,
            )
        )
    else:
        checks.append(
            DataHealthCheck(
                check_id="CHK-TRANSACTION-CLUSTER",
                subject_id=", ".join(derived_txn_ids),
                status="matched" if derived_txn_ids == referenced_txn_ids else "divergence",
                derived_value=derived_txn_ids,
                reference_value=referenced_txn_ids,
                source="08_BANK_TXN ↔ 14_ALERTS",
                message="Transactions at or above RR-001's threshold match the alert cluster.",
            )
        )

    execution_alert = _alert_by_type(alerts, "Contract execution risk")
    execution_contract_id = str(execution_alert["related_record"]) if execution_alert else "CON-004"
    execution_contract = _find(
        team_pack.get("04_CONTRACTS", []), "contract_id", execution_contract_id
    )
    if execution_alert is None or execution_contract is None:
        checks.append(
            _not_checked(
                "CHK-CONTRACT-SERVICE",
                execution_contract_id,
                "04_CONTRACTS ↔ 06_ORDERS ↔ 05_PRODUCTS",
                "Cross-check skipped because the contract or alert is absent.",
            )
        )
    else:
        feasibility = resolve_execution_feasibility(
            execution_contract,
            team_pack.get("06_ORDERS", []),
            team_pack.get("05_PRODUCTS", []),
            policy,
        )
        status = (
            "matched"
            if feasibility.execution_feasible is True
            else "not_checked"
            if feasibility.execution_feasible is None
            else "divergence"
        )
        checks.append(
            DataHealthCheck(
                check_id="CHK-CONTRACT-SERVICE",
                subject_id=execution_contract_id,
                status=status,
                derived_value=feasibility.execution_feasible,
                reference_value=(
                    f"service_list_price_vnd={feasibility.matched_service_list_price_vnd}"
                ),
                source="04_CONTRACTS ↔ 06_ORDERS ↔ 05_PRODUCTS",
                message=(
                    "The ordered service price matches contract value; this confirms value "
                    "alignment, not delivery-capacity risk."
                ),
            )
        )

    assessments = derive_credit_assessments(credit_cases, policy)
    for divergence in (item for item in assessments if item.divergence_id is not None):
        checks.append(
            DataHealthCheck(
                check_id=divergence.divergence_id or "DIV-UNKNOWN",
                subject_id=divergence.credit_case_id,
                status="divergence",
                derived_value=divergence.derived_decision,
                reference_value=divergence.raw_approval_status,
                source="DT-2 resolver ↔ 10_CREDIT_PROFILE ↔ 14_ALERTS",
                message=(
                    "The resolver holds the case because evidence is missing and eligibility "
                    "is below policy, while the source approval_status remains Review."
                ),
            )
        )

    return DataHealthReport(
        checks=checks,
        matched_count=sum(check.status == "matched" for check in checks),
        divergence_count=sum(check.status == "divergence" for check in checks),
        not_checked_count=sum(check.status == "not_checked" for check in checks),
    )


def build_risk_output(
    team_pack: Mapping[str, Sequence[Record]],
    policy: PolicyConfig,
    source_workbook: str,
) -> RiskOutput:
    invoice_priority, high_risk, issues = rank_open_invoices(
        team_pack.get("07_INVOICES", []), team_pack.get("03_CUSTOMERS", [])
    )
    execution_contract_ids = {
        str(alert["related_record"])
        for alert in team_pack.get("14_ALERTS", [])
        if str(alert.get("alert_type", "")).casefold() == "contract execution risk"
    }
    contracts = [
        contract
        for contract in team_pack.get("04_CONTRACTS", [])
        if str(contract["contract_id"]) in execution_contract_ids
    ]
    execution = [
        resolve_execution_feasibility(
            contract,
            team_pack.get("06_ORDERS", []),
            team_pack.get("05_PRODUCTS", []),
            policy,
        )
        for contract in contracts
    ]
    issues.extend(issue for result in execution for issue in result.issues)
    return RiskOutput(
        source_workbook=source_workbook,
        invoice_priority=invoice_priority,
        high_risk_invoice_id=high_risk,
        execution_feasibility=execution,
        credit_assessments=derive_credit_assessments(
            team_pack.get("10_CREDIT_PROFILE", []), policy
        ),
        data_health=build_data_health_report(team_pack, policy),
        issues=issues,
    )
