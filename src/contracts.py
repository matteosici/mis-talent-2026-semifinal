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


class FinanceOutput(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_workbook: str
    cashflow: CashflowReport
    open_receivables_vnd: int = Field(ge=0)
    open_receivables_basis: Literal["sum(invoice_amount_vnd where status = Open)"] = (
        "sum(invoice_amount_vnd where status = Open)"
    )
    issues: list[ValidationIssue] = Field(default_factory=list)


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
    derived_decision: Literal["Proceed to recommendation", "Hold — No recommendation"]
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
    issues: list[ValidationIssue] = Field(default_factory=list)


class DictionaryValidationResult(ContractModel):
    matched_columns: list[str]
    missing_columns: list[str]
    excluded_columns: list[str]
    issues: list[ValidationIssue] = Field(default_factory=list)
