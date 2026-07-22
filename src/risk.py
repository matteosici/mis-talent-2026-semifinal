"""D1 step 4 / D5 Risk & Compliance Agent logic."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    BusinessRuleSnapshot,
    CreditRiskFlag,
    ExecutionRisk,
    GovernanceFlag,
    PolicyConfig,
    RiskHandoff,
    SafeHandlingNote,
    TransactionCluster,
    TransactionHoldPayload,
    TransactionRiskFinding,
)
from .resolvers import evidence_missing
from .rules import get_resolved_rule
from .security import build_safe_handling_notes, safe_handle_value


Record = Mapping[str, Any]
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def normalize_transaction_pattern(description: str | None) -> str:
    text = _TIME_RE.sub("", (description or "").casefold())
    tokens = [
        token
        for token in _NON_WORD_RE.split(text)
        if token and token not in {"at", "retry"}
    ]
    return " ".join(tokens)


def _criteria(left: Record, right: Record) -> list[str]:
    criteria: list[str] = []
    if str(left.get("txn_date")) == str(right.get("txn_date")):
        criteria.append("same_day")
    if str(left.get("counterparty_id")) == str(right.get("counterparty_id")):
        criteria.append("same_counterparty")
    if normalize_transaction_pattern(left.get("description")) == normalize_transaction_pattern(
        right.get("description")
    ):
        criteria.append("same_pattern")
    return criteria


def analyze_transaction_risk(
    transactions: Sequence[Record],
    alerts: Sequence[Record],
    rules: BusinessRuleSnapshot,
    data_class_rows: Sequence[Record],
    masking_examples: Sequence[Record],
) -> tuple[list[TransactionRiskFinding], list[TransactionCluster]]:
    rr001 = get_resolved_rule(rules, "RR-001")
    risky = [
        txn
        for txn in transactions
        if float(txn.get("transaction_risk_score", 0))
        >= rules.transaction_risk_threshold
    ]
    findings: list[TransactionRiskFinding] = []
    for txn in risky:
        account = safe_handle_value(
            "account_id", txn.get("account_id"), data_class_rows, masking_examples
        )
        counterparty = safe_handle_value(
            "counterparty_id",
            txn.get("counterparty_id"),
            data_class_rows,
            masking_examples,
        )
        findings.append(
            TransactionRiskFinding(
                txn_id=str(txn["txn_id"]),
                txn_date=str(txn.get("txn_date")),
                direction=str(txn.get("direction", "")),
                amount_vnd=int(txn.get("amount", 0)),
                exposure_vnd=abs(int(txn.get("amount", 0))),
                risk_score=float(txn.get("transaction_risk_score", 0)),
                threshold=rules.transaction_risk_threshold,
                severity=rr001.severity,
                action=rr001.required_action,
                account_token=account.tokenized_value or account.masked_value or "[REDACTED]",
                counterparty_token=(
                    counterparty.tokenized_value
                    or counterparty.masked_value
                    or "[REDACTED]"
                ),
                normalized_pattern=normalize_transaction_pattern(txn.get("description")),
            )
        )

    # Connect risky transactions whenever at least two of D5's three criteria match.
    adjacency = {index: set() for index in range(len(risky))}
    pair_criteria: dict[tuple[int, int], list[str]] = {}
    for left_index in range(len(risky)):
        for right_index in range(left_index + 1, len(risky)):
            matched = _criteria(risky[left_index], risky[right_index])
            pair_criteria[(left_index, right_index)] = matched
            if len(matched) >= 2:
                adjacency[left_index].add(right_index)
                adjacency[right_index].add(left_index)

    components: list[list[int]] = []
    visited: set[int] = set()
    for start in adjacency:
        if start in visited or not adjacency[start]:
            continue
        stack = [start]
        component: list[int] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)
        components.append(sorted(component))

    clusters: list[TransactionCluster] = []
    for number, component in enumerate(components, start=1):
        component_rows = [risky[index] for index in component]
        matched_union: set[str] = set()
        for left_pos, left_index in enumerate(component):
            for right_index in component[left_pos + 1 :]:
                key = (min(left_index, right_index), max(left_index, right_index))
                matched_union.update(pair_criteria.get(key, []))
        txn_ids = sorted(str(row["txn_id"]) for row in component_rows)
        alert = next(
            (
                row
                for row in alerts
                if str(row.get("alert_type", "")).casefold() == "transaction anomaly"
                and set(txn_ids).issubset(
                    {
                        part.strip()
                        for part in str(row.get("related_record", "")).split(",")
                    }
                )
            ),
            None,
        )
        alert_ids = (
            set()
            if alert is None
            else {
                part.strip()
                for part in str(alert.get("related_record", "")).split(",")
                if part.strip()
            }
        )
        severity = str(alert.get("severity", rr001.severity)) if alert else rr001.severity
        clusters.append(
            TransactionCluster(
                cluster_id=f"CLUSTER-{number:03d}",
                txn_ids=txn_ids,
                matched_criteria=sorted(matched_union),
                criteria_match_count=len(matched_union),
                total_exposure_vnd=sum(abs(int(row.get("amount", 0))) for row in component_rows),
                severity=severity,
                alert_id=None if alert is None else str(alert.get("alert_id")),
                alert_consistent=None if alert is None else alert_ids == set(txn_ids),
                founder_approval_required=True,
                hold_payload=TransactionHoldPayload(txn_ids=txn_ids),
            )
        )
    return findings, clusters


def build_governance_flags(
    cases: Sequence[Record], rules: BusinessRuleSnapshot, policy: PolicyConfig
) -> tuple[list[GovernanceFlag], list[CreditRiskFlag]]:
    governance: list[GovernanceFlag] = []
    credit_flags: list[CreditRiskFlag] = []
    for case in cases:
        case_id = str(case["credit_case_id"])
        amount = int(case["requested_amount"])
        score = float(case["eligibility_score"])
        missing = evidence_missing(case.get("precheck_note"), policy.evidence_missing_markers)
        if amount > rules.governance_amount_threshold_vnd:
            governance.append(
                GovernanceFlag(
                    record_id=case_id,
                    record_type="credit_case",
                    amount_vnd=amount,
                    threshold_vnd=rules.governance_amount_threshold_vnd,
                    human_approval_required=True,
                    blocked_by_missing_evidence=missing,
                    reason=(
                        f"{case_id} requested_amount_vnd {amount} exceeds RR-005 "
                        f"threshold {rules.governance_amount_threshold_vnd}."
                    ),
                )
            )
        if score < rules.credit_min_eligibility_score:
            credit_flags.append(
                CreditRiskFlag(
                    credit_case_id=case_id,
                    eligibility_score=score,
                    threshold=rules.credit_min_eligibility_score,
                    evidence_missing=missing,
                    disposition="hold" if missing else "borderline",
                )
            )
    return governance, credit_flags


def build_execution_risks(
    orders: Sequence[Record], rules: BusinessRuleSnapshot, policy: PolicyConfig
) -> list[ExecutionRisk]:
    flagged: list[tuple[Record, list[str]]] = []
    for order in orders:
        status = str(order.get("status", ""))
        note = str(order.get("delivery_note", ""))
        markers: list[str] = []
        if status.casefold() == "at risk":
            markers.append("At risk")
        for marker in ("resource bottleneck", "needs extra contractor"):
            if marker in note.casefold():
                markers.append(marker)
        if markers:
            flagged.append((order, markers))

    contract_counts: dict[str, int] = {}
    for order, _ in flagged:
        contract_id = str(order.get("contract_id"))
        contract_counts[contract_id] = contract_counts.get(contract_id, 0) + 1

    return [
        ExecutionRisk(
            order_id=str(order["order_id"]),
            contract_id=str(order["contract_id"]),
            status=str(order.get("status", "")),
            delivery_note=str(order.get("delivery_note", "")),
            order_revenue_vnd=int(order.get("order_revenue", 0)),
            risk_markers=markers,
            systemic=contract_counts[str(order.get("contract_id"))] >= 2,
            late_delivery_days_threshold=rules.late_delivery_days_threshold,
            penalty_rate=policy.late_delivery_penalty_rate,
            potential_penalty_vnd_per_day=round(
                int(order.get("order_revenue", 0)) * policy.late_delivery_penalty_rate
            ),
        )
        for order, markers in flagged
    ]


def build_report_safe_handling_notes(
    team_pack: Mapping[str, Sequence[Record]],
    risky_transactions: Sequence[Record],
) -> list[SafeHandlingNote]:
    con004 = next(
        (
            contract
            for contract in team_pack.get("04_CONTRACTS", [])
            if str(contract.get("contract_id")) == "CON-004"
        ),
        {},
    )
    first_risky = risky_transactions[0] if risky_transactions else {}
    access_example = next(
        (
            row.get("raw_example")
            for row in team_pack.get("21_MASKING_EXAMPLES", [])
            if str(row.get("source_field")) == "access_token"
        ),
        "mock-token",
    )
    values = {
        "customer_id": con004.get("customer_id"),
        "account_id": first_risky.get("account_id"),
        "counterparty_id": first_risky.get("counterparty_id"),
        "contract_value": con004.get("contract_value"),
        "access_token": access_example,
    }
    return build_safe_handling_notes(
        values,
        team_pack.get("20_DATA_CLASS", []),
        team_pack.get("21_MASKING_EXAMPLES", []),
    )


def build_risk_handoff(
    findings: Sequence[TransactionRiskFinding],
    clusters: Sequence[TransactionCluster],
    governance: Sequence[GovernanceFlag],
    credit_flags: Sequence[CreditRiskFlag],
    execution_risks: Sequence[ExecutionRisk],
    safe_notes: Sequence[SafeHandlingNote],
) -> RiskHandoff:
    primary_cluster = clusters[0] if clusters else None
    if primary_cluster is not None:
        hold_payload = primary_cluster.hold_payload
        hold_amount = primary_cluster.total_exposure_vnd
        hold_severity = primary_cluster.severity
        hold_source = "cluster"
        hold_txn_ids = primary_cluster.txn_ids
    else:
        hold_findings = [
            item for item in findings if item.severity.casefold() == "critical"
        ]
        if not hold_findings:
            hold_payload = None
            hold_amount = 0
            hold_severity = None
            hold_source = None
            hold_txn_ids = []
        else:
            hold_txn_ids = [item.txn_id for item in hold_findings]
            hold_payload = TransactionHoldPayload(txn_ids=hold_txn_ids)
            hold_amount = sum(item.exposure_vnd for item in hold_findings)
            hold_severity = "Critical"
            hold_source = "single_finding"

    paused = hold_payload is not None and (hold_severity or "").casefold() == "critical"
    return RiskHandoff(
        transaction_hold=hold_payload,
        transaction_hold_source=hold_source,
        transaction_hold_txn_ids=hold_txn_ids,
        transaction_hold_amount_vnd=hold_amount,
        transaction_hold_severity=hold_severity,
        approval_requirement_record_ids=[item.record_id for item in governance],
        credit_risk_record_ids=[item.credit_case_id for item in credit_flags],
        execution_risk_order_ids=[item.order_id for item in execution_risks],
        safe_handling_fields=[item.field_name for item in safe_notes],
        financial_flow_paused=paused,
    )
