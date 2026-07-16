"""Pure, policy-driven resolvers for the eight documented specification gaps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    BusinessRuleSnapshot,
    CashflowReport,
    CreditCandidate,
    CreditPlan,
    CreditAssessment,
    ExecutionFeasibility,
    FinanceOutput,
    FinanceHandoff,
    InvoicePriorityItem,
    MarginAssessment,
    MonthCashflow,
    PolicyConfig,
    ReceivableAgingReport,
    ValidationIssue,
)
from .rules import resolve_business_rules
from .team_pack import audit_ds1_sources


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
        reserve_gap = reserve - closing
        if not breach:
            severity = None
        elif reserve_gap > policy.critical_gap_threshold_vnd:
            severity = "Critical"
        elif reserve_gap >= policy.high_gap_threshold_vnd:
            severity = "High"
        else:
            severity = "Medium"
        months.append(
            MonthCashflow(
                month=str(row["month"]),
                expected_cash_in_vnd=cash_in,
                expected_cash_out_vnd=cash_out,
                cash_reserve_minimum_vnd=reserve,
                closing_cash_vnd=closing,
                reserve_gap_vnd=reserve_gap,
                funding_need_vnd=cash_out + reserve - cash_in,
                breach=breach,
                severity=severity,
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
    rule_snapshot = resolve_business_rules(team_pack.get("13_RISK_RULES", []), policy)
    effective_policy = policy.model_copy(
        update={"credit_min_eligibility_score": rule_snapshot.credit_min_eligibility_score}
    )
    cashflow = build_cashflow_report(team_pack["09_CASHFLOW"], effective_policy)
    receivables, receivable_issues = build_receivable_aging(team_pack)
    margin_analysis = build_margin_analysis(
        team_pack.get("04_CONTRACTS", []), rule_snapshot.margin_threshold
    )
    credit_candidates = build_credit_candidates(
        team_pack.get("10_CREDIT_PROFILE", []), rule_snapshot, effective_policy
    )
    credit_plan = build_credit_plan(
        credit_candidates,
        cashflow.worst_month_funding_need_vnd,
    )
    source_audit = audit_ds1_sources(dict(team_pack))
    issues = [*rule_snapshot.issues, *receivable_issues]
    for sheet in source_audit.missing_sheets:
        issues.append(
            ValidationIssue(
                code="DS1_SOURCE_MISSING",
                record_id=sheet,
                message=f"Required DS1 source sheet {sheet} is missing.",
            )
        )

    profile_target = next(
        (
            float(row["value"])
            for row in team_pack.get("02_OPC_PROFILE", [])
            if str(row.get("field")) == "target_gross_margin"
        ),
        None,
    )
    if profile_target is not None and profile_target != rule_snapshot.margin_threshold:
        issues.append(
            ValidationIssue(
                code="MARGIN_THRESHOLD_DIVERGENCE",
                record_id="RR-003",
                field="target_gross_margin",
                message=(
                    f"02_OPC_PROFILE target {profile_target} differs from RR-003 "
                    f"threshold {rule_snapshot.margin_threshold}; RR-003 controls alerts."
                ),
            )
        )

    margin_warning_ids = [item.contract_id for item in margin_analysis if item.warning]
    candidate_ids = [
        item.credit_case_id for item in credit_candidates if item.candidate_status != "hold"
    ]
    handoff = FinanceHandoff(
        funding_gap_by_month_vnd={
            month.month: month.funding_need_vnd for month in cashflow.months
        },
        worst_month=cashflow.worst_month,
        worst_month_basis=cashflow.worst_month_basis,
        open_invoices_total_vnd=receivables.open_invoices_total_vnd,
        high_risk_invoice_id=receivables.high_risk_invoice_id,
        critical_dependency_invoice_id=receivables.critical_dependency_invoice_id,
        margin_warning_contract_ids=margin_warning_ids,
        credit_candidate_ids=candidate_ids,
        priority_bridge_amount_vnd=credit_plan.priority_bridge_amount_vnd,
        decision_package_total_ask_vnd=credit_plan.decision_package_total_ask_vnd,
    )
    return FinanceOutput(
        source_workbook=source_workbook,
        cashflow=cashflow,
        open_receivables_vnd=receivables.open_invoices_total_vnd,
        source_audit=source_audit,
        rule_snapshot=rule_snapshot,
        receivable_aging=receivables,
        margin_analysis=margin_analysis,
        credit_candidates=credit_candidates,
        credit_plan=credit_plan,
        d5_handoff=handoff,
        issues=issues,
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


def build_receivable_aging(
    team_pack: Mapping[str, Sequence[Record]],
) -> tuple[ReceivableAgingReport, list[ValidationIssue]]:
    invoices = team_pack.get("07_INVOICES", [])
    priority, high_risk, issues = rank_open_invoices(
        invoices, team_pack.get("03_CUSTOMERS", [])
    )
    totals = {"paid": 0, "open": 0, "not issued": 0}
    for invoice in invoices:
        status = str(invoice.get("status", "")).casefold()
        if status in totals:
            totals[status] += int(invoice.get("invoice_amount", 0))

    not_issued = [
        invoice
        for invoice in invoices
        if str(invoice.get("status", "")).casefold() == "not issued"
    ]
    critical = max(
        not_issued,
        key=lambda invoice: int(invoice.get("invoice_amount", 0)),
        default=None,
    )
    critical_contract_id: str | None = None
    if critical:
        order = next(
            (
                row
                for row in team_pack.get("06_ORDERS", [])
                if str(row.get("order_id")) == str(critical.get("order_id"))
            ),
            None,
        )
        critical_contract_id = None if order is None else str(order.get("contract_id"))
        if order is None:
            issues.append(
                ValidationIssue(
                    code="INVOICE_ORDER_NOT_FOUND",
                    record_id=str(critical.get("invoice_id")),
                    field="order_id",
                    message="Critical not-issued invoice cannot be traced to a contract.",
                )
            )

    return (
        ReceivableAgingReport(
            paid_invoices_total_vnd=totals["paid"],
            open_invoices_total_vnd=totals["open"],
            not_issued_invoices_total_vnd=totals["not issued"],
            priority_invoices=priority,
            high_risk_invoice_id=high_risk,
            critical_dependency_invoice_id=(
                None if critical is None else str(critical.get("invoice_id"))
            ),
            critical_dependency_contract_id=critical_contract_id,
            critical_dependency_basis=(
                "largest Not issued invoice; contract resolved through 06_ORDERS"
            ),
        ),
        issues,
    )


def build_margin_analysis(
    contracts: Sequence[Record], target_margin: float
) -> list[MarginAssessment]:
    return [
        MarginAssessment(
            contract_id=str(contract["contract_id"]),
            contract_value_vnd=int(contract["contract_value"]),
            gross_margin=float(contract["gross_margin"]),
            target_margin=target_margin,
            margin_gap=round(float(contract["gross_margin"]) - target_margin, 4),
            gross_profit_vnd=round(
                int(contract["contract_value"]) * float(contract["gross_margin"])
            ),
            warning=float(contract["gross_margin"]) < target_margin,
        )
        for contract in contracts
    ]


def build_credit_candidates(
    cases: Sequence[Record],
    rules: BusinessRuleSnapshot,
    policy: PolicyConfig,
) -> list[CreditCandidate]:
    candidates: list[CreditCandidate] = []
    for case in cases:
        score = float(case["eligibility_score"])
        missing = evidence_missing(case.get("precheck_note"), policy.evidence_missing_markers)
        amount = int(case["requested_amount"])
        rule_ids: list[str] = []
        if amount > rules.governance_amount_threshold_vnd:
            rule_ids.append("RR-005")
        if score < rules.credit_min_eligibility_score:
            rule_ids.append("RR-006")
        status = (
            "hold"
            if missing
            else "borderline"
            if score < rules.credit_min_eligibility_score
            else "candidate"
        )
        candidates.append(
            CreditCandidate(
                credit_case_id=str(case["credit_case_id"]),
                request_type=str(case["request_type"]),
                requested_amount_vnd=amount,
                eligibility_score=score,
                candidate_status=status,
                precheck_note=str(case.get("precheck_note", "")),
                evidence_missing=missing,
                human_approval_required=amount > rules.governance_amount_threshold_vnd,
                rule_ids=rule_ids,
            )
        )

    ordered_active = sorted(
        (item for item in candidates if item.candidate_status != "hold"),
        key=lambda item: (-item.eligibility_score, item.credit_case_id),
    )
    ranks = {item.credit_case_id: rank for rank, item in enumerate(ordered_active, start=1)}
    ranked = [
        item.model_copy(update={"priority_rank": ranks.get(item.credit_case_id)})
        for item in candidates
    ]
    return sorted(
        ranked,
        key=lambda item: (
            item.priority_rank is None,
            item.priority_rank if item.priority_rank is not None else 999,
            item.credit_case_id,
        ),
    )


def build_credit_plan(
    candidates: Sequence[CreditCandidate], funding_target_vnd: int
) -> CreditPlan:
    active = [item for item in candidates if item.candidate_status != "hold"]
    bridge: list[CreditCandidate] = []
    bridge_total = 0
    for item in active:
        if bridge_total + item.requested_amount_vnd <= funding_target_vnd:
            bridge.append(item)
            bridge_total += item.requested_amount_vnd

    main_working_capital = next(
        (
            item
            for item in active
            if "working capital line" in item.request_type.casefold()
            and "micro" not in item.request_type.casefold()
        ),
        None,
    )
    performance_bond = next(
        (item for item in active if "performance bond" in item.request_type.casefold()),
        None,
    )
    decision_package = [
        item for item in (main_working_capital, performance_bond) if item is not None
    ]
    return CreditPlan(
        funding_target_vnd=funding_target_vnd,
        priority_bridge_credit_case_ids=[item.credit_case_id for item in bridge],
        priority_bridge_amount_vnd=bridge_total,
        priority_bridge_shortfall_vnd=max(funding_target_vnd - bridge_total, 0),
        decision_package_credit_case_ids=[
            item.credit_case_id for item in decision_package
        ],
        decision_package_total_ask_vnd=sum(
            item.requested_amount_vnd for item in decision_package
        ),
        held_credit_case_ids=[
            item.credit_case_id for item in candidates if item.candidate_status == "hold"
        ],
    )


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
                    "Hold — No recommendation"
                    if missing
                    else "Proceed to recommendation"
                    if proceed
                    else "Candidate — Borderline"
                ),
                derived_decision_basis=decision_basis,
                divergence_id=divergence_id,
            )
        )
    return assessments
