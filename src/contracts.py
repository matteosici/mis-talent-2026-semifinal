"""Frozen producer contracts shared by the finance and risk lanes.

The public field names in this module are the integration boundary. Until the
competition freeze, changes should be additive only: do not rename or remove a
field. Policy choices belong in ``config/policies.yaml`` and are surfaced by a
``*_basis`` field instead of changing the payload shape.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Strict producer-side model used to catch accidental contract drift."""

    model_config = ConfigDict(extra="forbid")


IssueSeverity = Literal["info", "warning", "error"]


class ValidationIssue(ContractModel):
    code: str
    message: str
    severity: IssueSeverity = "warning"
    record_id: str | None = None
    field: str | None = None


class PolicyConfig(ContractModel):
    worst_month_basis: Literal["funding_need", "reserve_gap"] = "funding_need"
    evidence_missing_markers: tuple[str, ...] = (
        "missing",
        "not provided",
        "absent",
        "thiếu",
        "chưa có",
    )
    credit_min_eligibility_score: float = Field(default=0.65, ge=0, le=1)
    reserve_breach_severity: Literal["Medium", "High", "Critical"] = "High"
    service_value_tolerance_vnd: int = Field(default=0, ge=0)
    transaction_risk_threshold: int = Field(default=85, ge=0, le=100)
    margin_threshold: float = Field(default=0.28, ge=0, le=1)
    governance_amount_threshold_vnd: int = Field(default=300_000_000, ge=0)
    late_delivery_days_threshold: int = Field(default=7, ge=0)
    late_delivery_penalty_rate: float = Field(default=0.015, ge=0, le=1)
    high_gap_threshold_vnd: int = Field(default=200_000_000, ge=0)
    critical_gap_threshold_vnd: int = Field(default=500_000_000, ge=0)


class SourceAudit(ContractModel):
    row_counts: dict[str, int]
    loaded_sheets: list[str]
    missing_sheets: list[str]
    core_complete: bool


class ResolvedRule(ContractModel):
    rule_id: str
    operator: Literal[">", ">=", "<", "<=", "=="]
    threshold: int | float
    trigger_condition: str
    severity: str
    required_action: str
    source: Literal["13_RISK_RULES", "policy_fallback"]


class BusinessRuleSnapshot(ContractModel):
    transaction_risk_threshold: int = Field(ge=0, le=100)
    margin_threshold: float = Field(ge=0, le=1)
    governance_amount_threshold_vnd: int = Field(ge=0)
    credit_min_eligibility_score: float = Field(ge=0, le=1)
    late_delivery_days_threshold: int = Field(ge=0)
    applied_rules: list[ResolvedRule]
    issues: list[ValidationIssue] = Field(default_factory=list)


class MonthCashflow(ContractModel):
    month: str
    expected_cash_in_vnd: int = Field(ge=0)
    expected_cash_out_vnd: int = Field(ge=0)
    cash_reserve_minimum_vnd: int = Field(ge=0)
    closing_cash_vnd: int
    reserve_gap_vnd: int
    reserve_gap_basis: Literal[
        "cash_reserve_minimum_vnd - closing_cash_vnd"
    ] = "cash_reserve_minimum_vnd - closing_cash_vnd"
    funding_need_vnd: int
    funding_need_basis: Literal[
        "expected_cash_out_vnd + cash_reserve_minimum_vnd - expected_cash_in_vnd"
    ] = "expected_cash_out_vnd + cash_reserve_minimum_vnd - expected_cash_in_vnd"
    breach: bool
    breach_basis: Literal[
        "closing_cash_vnd < cash_reserve_minimum_vnd"
    ] = "closing_cash_vnd < cash_reserve_minimum_vnd"
    severity: Literal["Medium", "High", "Critical"] | None


class CashflowReport(ContractModel):
    months: list[MonthCashflow]
    breach_count: int = Field(ge=0)
    breach_count_basis: Literal["count(months where breach = true)"] = (
        "count(months where breach = true)"
    )
    worst_month: str
    worst_month_basis: Literal["funding_need", "reserve_gap"]
    worst_month_funding_need_vnd: int
    worst_month_reserve_gap_vnd: int


class CustomerIntakeStatus(ContractModel):
    contract_id: str
    customer_id: str
    verified: bool
    flag: Literal["unverified", "customer_id_missing"] | None = None
    payment_reliability: float | None = Field(default=None, ge=0, le=1)
    basis: Literal["customer_id existence in 03_CUSTOMERS"] = (
        "customer_id existence in 03_CUSTOMERS"
    )


class FinanceOutput(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_workbook: str
    cashflow: CashflowReport
    open_receivables_vnd: int = Field(ge=0)
    open_receivables_basis: Literal["sum(invoice_amount_vnd where status = Open)"] = (
        "sum(invoice_amount_vnd where status = Open)"
    )
    source_audit: SourceAudit | None = None
    rule_snapshot: BusinessRuleSnapshot | None = None
    intake: list[CustomerIntakeStatus] = Field(default_factory=list)
    feasibility: list["ExecutionFeasibility"] = Field(default_factory=list)
    receivable_aging: "ReceivableAgingReport | None" = None
    margin_analysis: list["MarginAssessment"] = Field(default_factory=list)
    credit_candidates: list["CreditCandidate"] = Field(default_factory=list)
    credit_plan: "CreditPlan | None" = None
    d5_handoff: "FinanceHandoff | None" = None
    issues: list[ValidationIssue] = Field(default_factory=list)


class ReceivableAgingReport(ContractModel):
    paid_invoices_total_vnd: int = Field(ge=0)
    open_invoices_total_vnd: int = Field(ge=0)
    not_issued_invoices_total_vnd: int = Field(ge=0)
    priority_invoices: list["InvoicePriorityItem"]
    high_risk_invoice_id: str | None
    critical_dependency_invoice_id: str | None
    critical_dependency_contract_id: str | None
    critical_dependency_basis: str


class MarginAssessment(ContractModel):
    contract_id: str
    status: str | None = None
    contract_value_vnd: int = Field(ge=0)
    gross_margin: float = Field(ge=0, le=1)
    target_margin: float = Field(ge=0, le=1)
    margin_gap: float
    gross_profit_vnd: int
    warning: bool
    rule_id: Literal["RR-003"] = "RR-003"
    margin_basis: Literal["gross_margin < RR-003 threshold"] = (
        "gross_margin < RR-003 threshold"
    )


class CreditCandidate(ContractModel):
    credit_case_id: str
    request_type: str
    requested_amount_vnd: int = Field(ge=0)
    eligibility_score: float = Field(ge=0, le=1)
    priority_rank: int | None = Field(default=None, ge=1)
    candidate_status: Literal["candidate", "borderline", "hold"]
    precheck_note: str
    evidence_missing: bool
    human_approval_required: bool
    rule_ids: list[str]


class CreditPlan(ContractModel):
    funding_target_vnd: int
    funding_target_basis: Literal["worst_month_funding_need_vnd"] = (
        "worst_month_funding_need_vnd"
    )
    priority_bridge_credit_case_ids: list[str]
    priority_bridge_amount_vnd: int = Field(ge=0)
    priority_bridge_shortfall_vnd: int = Field(ge=0)
    priority_bridge_basis: Literal[
        "top eligible candidates until closest non-exceeding funding target"
    ] = "top eligible candidates until closest non-exceeding funding target"
    decision_package_credit_case_ids: list[str]
    decision_package_total_ask_vnd: int = Field(ge=0)
    decision_package_basis: Literal["main working capital line + performance bond"] = (
        "main working capital line + performance bond"
    )
    held_credit_case_ids: list[str]


class FinanceHandoff(ContractModel):
    # Legacy alias kept for schema compatibility; values equal funding_need_by_month_vnd.
    funding_gap_by_month_vnd: dict[str, int]
    funding_need_by_month_vnd: dict[str, int]
    reserve_gap_by_month_vnd: dict[str, int]
    worst_month: str
    worst_month_basis: Literal["funding_need", "reserve_gap"]
    open_invoices_total_vnd: int = Field(ge=0)
    high_risk_invoice_id: str | None
    critical_dependency_invoice_id: str | None
    margin_warning_contract_ids: list[str]
    credit_candidate_ids: list[str]
    priority_bridge_amount_vnd: int = Field(ge=0)
    decision_package_total_ask_vnd: int = Field(ge=0)
    customer_verified: bool = True
    customer_verified_basis: Literal[
        "all new-opportunity customers exist in 03_CUSTOMERS"
    ] = "all new-opportunity customers exist in 03_CUSTOMERS"
    execution_feasible: bool | None = None
    execution_feasible_basis: Literal[
        "false if any new opportunity is infeasible; null if any is unknown; true otherwise"
    ] = (
        "false if any new opportunity is infeasible; null if any is unknown; true otherwise"
    )


class ExecutionFeasibility(ContractModel):
    contract_id: str
    service_ids: list[str]
    matched_service_list_price_vnd: int | None
    execution_feasible: bool | None
    execution_feasibility_basis: Literal[
        "sum_unique_service_list_price_vnd matches contract_value_vnd"
    ] = "sum_unique_service_list_price_vnd matches contract_value_vnd"
    issues: list[ValidationIssue] = Field(default_factory=list)


class InvoicePriorityItem(ContractModel):
    invoice_id: str
    customer_id: str
    invoice_amount_vnd: int = Field(ge=0)
    payment_reliability: float | None = Field(default=None, ge=0, le=1)
    priority_rank: int = Field(ge=1)
    risk_rank: int = Field(ge=1)


class CreditAssessment(ContractModel):
    credit_case_id: str
    eligibility_score: float = Field(ge=0, le=1)
    evidence_missing: bool
    evidence_missing_basis: str
    raw_approval_status: str
    derived_decision: Literal[
        "Proceed to recommendation",
        "Candidate — Borderline",
        "Hold — No recommendation",
    ]
    derived_decision_basis: str
    divergence_id: str | None = None


ScalarOrList = str | int | float | bool | list[str] | None


class DataHealthCheck(ContractModel):
    check_id: str
    subject_id: str
    status: Literal["matched", "divergence", "not_checked"]
    derived_value: ScalarOrList
    reference_value: ScalarOrList
    source: str
    message: str


class DataHealthReport(ContractModel):
    checks: list[DataHealthCheck]
    matched_count: int = Field(ge=0)
    divergence_count: int = Field(ge=0)
    not_checked_count: int = Field(ge=0)


class RiskOutput(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_workbook: str
    invoice_priority_basis: Literal["invoice_amount_vnd descending"] = (
        "invoice_amount_vnd descending"
    )
    invoice_priority: list[InvoicePriorityItem]
    high_risk_invoice_id: str | None
    high_risk_basis: Literal["minimum known payment_reliability"] = (
        "minimum known payment_reliability"
    )
    execution_feasibility: list[ExecutionFeasibility]
    credit_assessments: list[CreditAssessment]
    data_health: DataHealthReport
    source_audit: SourceAudit | None = None
    rule_snapshot: BusinessRuleSnapshot | None = None
    transaction_findings: list["TransactionRiskFinding"] = Field(default_factory=list)
    transaction_clusters: list["TransactionCluster"] = Field(default_factory=list)
    governance_flags: list["GovernanceFlag"] = Field(default_factory=list)
    credit_risk_flags: list["CreditRiskFlag"] = Field(default_factory=list)
    execution_risks: list["ExecutionRisk"] = Field(default_factory=list)
    safe_handling_notes: list["SafeHandlingNote"] = Field(default_factory=list)
    financial_flow_paused: bool = False
    d5_handoff: "RiskHandoff | None" = None
    issues: list[ValidationIssue] = Field(default_factory=list)


class TransactionRiskFinding(ContractModel):
    txn_id: str
    txn_date: str
    direction: str
    amount_vnd: int
    exposure_vnd: int = Field(ge=0)
    risk_score: float = Field(ge=0, le=100)
    threshold: float = Field(ge=0, le=100)
    rule_id: Literal["RR-001"] = "RR-001"
    severity: str
    action: str
    account_token: str
    counterparty_token: str
    normalized_pattern: str


class TransactionHoldPayload(ContractModel):
    txn_ids: list[str]
    action: Literal["temporary_hold"] = "temporary_hold"
    approver: Literal["founder_confirmation_required"] = (
        "founder_confirmation_required"
    )


class TransactionCluster(ContractModel):
    cluster_id: str
    txn_ids: list[str]
    matched_criteria: list[Literal["same_day", "same_counterparty", "same_pattern"]]
    criteria_match_count: int = Field(ge=0, le=3)
    total_exposure_vnd: int = Field(ge=0)
    severity: str
    alert_id: str | None
    alert_consistent: bool | None
    founder_approval_required: bool
    hold_payload: TransactionHoldPayload


class GovernanceFlag(ContractModel):
    record_id: str
    record_type: Literal["credit_case", "financial_decision"]
    amount_vnd: int = Field(ge=0)
    threshold_vnd: int = Field(ge=0)
    rule_id: Literal["RR-005"] = "RR-005"
    human_approval_required: bool
    blocked_by_missing_evidence: bool
    reason: str


class CreditRiskFlag(ContractModel):
    credit_case_id: str
    eligibility_score: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    rule_id: Literal["RR-006"] = "RR-006"
    evidence_missing: bool
    disposition: Literal["borderline", "hold"]


class ExecutionRisk(ContractModel):
    order_id: str
    contract_id: str
    status: str
    delivery_note: str
    order_revenue_vnd: int = Field(ge=0)
    risk_markers: list[str]
    systemic: bool
    late_delivery_days_threshold: int = Field(ge=0)
    penalty_rate: float = Field(ge=0, le=1)
    potential_penalty_vnd_per_day: int = Field(ge=0)
    penalty_basis: Literal["order_revenue_vnd * late_delivery_penalty_rate"] = (
        "order_revenue_vnd * late_delivery_penalty_rate"
    )
    rule_id: Literal["RR-007"] = "RR-007"


class SafeHandlingNote(ContractModel):
    field_name: str
    classification: str
    handling_rule: str
    masked_value: str | None
    tokenized_value: str | None
    source: Literal["20_DATA_CLASS + 21_MASKING_EXAMPLES"] = (
        "20_DATA_CLASS + 21_MASKING_EXAMPLES"
    )


class RiskHandoff(ContractModel):
    transaction_hold: TransactionHoldPayload | None
    transaction_hold_source: Literal["cluster", "single_finding"] | None = None
    transaction_hold_txn_ids: list[str] = Field(default_factory=list)
    transaction_hold_amount_vnd: int = Field(ge=0)
    transaction_hold_severity: str | None
    approval_requirement_record_ids: list[str]
    credit_risk_record_ids: list[str]
    execution_risk_order_ids: list[str]
    safe_handling_fields: list[str]
    financial_flow_paused: bool


class DictionaryValidationResult(ContractModel):
    matched_columns: list[str]
    missing_columns: list[str]
    excluded_columns: list[str]
    issues: list[ValidationIssue] = Field(default_factory=list)


class DS1BackendOutput(ContractModel):
    finance: FinanceOutput
    risk: RiskOutput




