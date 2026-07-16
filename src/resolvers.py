"""Pure, policy-driven resolvers for the eight documented specification gaps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    CashflowReport,
    CreditAssessment,
    ExecutionFeasibility,
    FinanceOutput,
    InvoicePriorityItem,
    MonthCashflow,
    PolicyConfig,
    ValidationIssue,
)


Record = Mapping[str, Any]


def evidence_missing(precheck_note: str | None, markers: Sequence[str]) -> bool:
    """Detect blocking evidence phrases without treating the word 'evidence' as blocking."""

    note = (precheck_note or "").casefold()
    return any(marker.casefold() in note for marker in markers)


def build_cashflow_report(rows: Sequence[Record], policy: PolicyConfig) -> CashflowReport:
    if not rows:
        raise ValueError("At least one cashflow row is required")

    months: list[MonthCashflow] = []
    for row in rows:
        cash_in = int(row["expected_cash_in"])
        cash_out = int(row["expected_cash_out"])
        reserve = int(row["cash_reserve_minimum"])
        closing = int(row["projected_closing_cash"])
        breach = closing < reserve
        months.append(
            MonthCashflow(
                month=str(row["month"]),
                expected_cash_in_vnd=cash_in,
                expected_cash_out_vnd=cash_out,
                cash_reserve_minimum_vnd=reserve,
                closing_cash_vnd=closing,
                reserve_gap_vnd=reserve - closing,
                funding_need_vnd=cash_out + reserve - cash_in,
                breach=breach,
                severity=policy.reserve_breach_severity if breach else None,
            )
        )

    metric = (
        (lambda item: item.funding_need_vnd)
        if policy.worst_month_basis == "funding_need"
        else (lambda item: item.reserve_gap_vnd)
    )
    worst = max(months, key=lambda item: (metric(item), item.month))
    return CashflowReport(
        months=months,
        breach_count=sum(item.breach for item in months),
        worst_month=worst.month,
        worst_month_basis=policy.worst_month_basis,
        worst_month_funding_need_vnd=worst.funding_need_vnd,
        worst_month_reserve_gap_vnd=worst.reserve_gap_vnd,
    )


def build_finance_output(
    team_pack: Mapping[str, Sequence[Record]],
    policy: PolicyConfig,
    source_workbook: str,
) -> FinanceOutput:
    cashflow = build_cashflow_report(team_pack["09_CASHFLOW"], policy)
    open_receivables = sum(
        int(invoice["invoice_amount"])
        for invoice in team_pack["07_INVOICES"]
        if str(invoice.get("status", "")).casefold() == "open"
    )
    return FinanceOutput(
        source_workbook=source_workbook,
        cashflow=cashflow,
        open_receivables_vnd=open_receivables,
    )


def resolve_execution_feasibility(
    contract: Record,
    orders: Sequence[Record],
    products: Sequence[Record],
    policy: PolicyConfig,
) -> ExecutionFeasibility:
    """Resolve service IDs via orders and fail soft when the join is incomplete.

    The boolean is deliberately narrow: it verifies value alignment with the
    unique ordered services. It does not claim that delivery capacity is proven.
    """

    contract_id = str(contract["contract_id"])
    service_ids = sorted(
        {
            str(order["service_id"])
            for order in orders
            if str(order.get("contract_id")) == contract_id and order.get("service_id")
        }
    )
    if not service_ids:
        issue = ValidationIssue(
            code="CONTRACT_ORDERS_NOT_FOUND",
            record_id=contract_id,
            field="service_id",
            message="No order links this contract to a service; feasibility is unknown.",
        )
        return ExecutionFeasibility(
            contract_id=contract_id,
            service_ids=[],
            matched_service_list_price_vnd=None,
            execution_feasible=None,
            issues=[issue],
        )

    product_map = {str(product["service_id"]): product for product in products}
    missing = [service_id for service_id in service_ids if service_id not in product_map]
    if missing:
        issue = ValidationIssue(
            code="SERVICE_NOT_FOUND",
            record_id=contract_id,
            field="service_id",
            message=f"Unknown service IDs: {', '.join(missing)}; feasibility is unknown.",
        )
        return ExecutionFeasibility(
            contract_id=contract_id,
            service_ids=service_ids,
            matched_service_list_price_vnd=None,
            execution_feasible=None,
            issues=[issue],
        )

    matched_value = sum(int(product_map[service_id]["list_price"]) for service_id in service_ids)
    contract_value = int(contract["contract_value"])
    feasible = abs(matched_value - contract_value) <= policy.service_value_tolerance_vnd
    return ExecutionFeasibility(
        contract_id=contract_id,
        service_ids=service_ids,
        matched_service_list_price_vnd=matched_value,
        execution_feasible=feasible,
    )


def rank_open_invoices(
    invoices: Sequence[Record],
    customers: Sequence[Record],
) -> tuple[list[InvoicePriorityItem], str | None, list[ValidationIssue]]:
    """Keep collection priority and counterparty risk as separate rankings."""

    customer_map = {str(customer["customer_id"]): customer for customer in customers}
    open_invoices = [
        invoice
        for invoice in invoices
        if str(invoice.get("status", "")).casefold() == "open"
    ]
    priority_order = sorted(
        open_invoices,
        key=lambda invoice: (-int(invoice["invoice_amount"]), str(invoice["invoice_id"])),
    )

    reliabilities: dict[str, float | None] = {}
    issues: list[ValidationIssue] = []
    for invoice in open_invoices:
        invoice_id = str(invoice["invoice_id"])
        customer_id = str(invoice["customer_id"])
        customer = customer_map.get(customer_id)
        if customer is None:
            reliabilities[invoice_id] = None
            issues.append(
                ValidationIssue(
                    code="CUSTOMER_NOT_FOUND",
                    record_id=customer_id,
                    field="customer_id",
                    message=(
                        f"Invoice {invoice_id} references an unknown customer; "
                        "risk rank is placed last."
                    ),
                )
            )
        else:
            value = customer.get("payment_reliability")
            reliabilities[invoice_id] = None if value is None else float(value)

    risk_order = sorted(
        open_invoices,
        key=lambda invoice: (
            reliabilities[str(invoice["invoice_id"])] is None,
            reliabilities[str(invoice["invoice_id"])]
            if reliabilities[str(invoice["invoice_id"])] is not None
            else float("inf"),
            str(invoice["invoice_id"]),
        ),
    )
    risk_rank = {
        str(invoice["invoice_id"]): rank for rank, invoice in enumerate(risk_order, start=1)
    }

    items = [
        InvoicePriorityItem(
            invoice_id=str(invoice["invoice_id"]),
            customer_id=str(invoice["customer_id"]),
            invoice_amount_vnd=int(invoice["invoice_amount"]),
            payment_reliability=reliabilities[str(invoice["invoice_id"])],
            priority_rank=rank,
            risk_rank=risk_rank[str(invoice["invoice_id"])],
        )
        for rank, invoice in enumerate(priority_order, start=1)
    ]
    high_risk = next(
        (
            str(invoice["invoice_id"])
            for invoice in risk_order
            if reliabilities[str(invoice["invoice_id"])] is not None
        ),
        None,
    )
    return items, high_risk, issues


def derive_credit_assessments(
    cases: Sequence[Record], policy: PolicyConfig
) -> list[CreditAssessment]:
    assessments: list[CreditAssessment] = []
    divergence_number = 0
    markers_label = "blocking marker in precheck_note"
    decision_basis = (
        f"eligibility_score >= {policy.credit_min_eligibility_score:g} "
        "and evidence_missing = false"
    )
    for case in cases:
        missing = evidence_missing(case.get("precheck_note"), policy.evidence_missing_markers)
        score = float(case["eligibility_score"])
        proceed = score >= policy.credit_min_eligibility_score and not missing
        raw_status = str(case.get("approval_status", ""))
        divergence_id: str | None = None
        if missing and raw_status.casefold() == "review":
            divergence_number += 1
            divergence_id = f"DIV-{divergence_number:03d}"
        assessments.append(
            CreditAssessment(
                credit_case_id=str(case["credit_case_id"]),
                eligibility_score=score,
                evidence_missing=missing,
                evidence_missing_basis=markers_label,
                raw_approval_status=raw_status,
                derived_decision=(
                    "Proceed to recommendation" if proceed else "Hold — No recommendation"
                ),
                derived_decision_basis=decision_basis,
                divergence_id=divergence_id,
            )
        )
    return assessments
