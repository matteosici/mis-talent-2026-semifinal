"""Resolve D5 business thresholds from the published risk-rule sheet."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    BusinessRuleSnapshot,
    PolicyConfig,
    ResolvedRule,
    ValidationIssue,
)


Record = Mapping[str, Any]
_THRESHOLD_RE = re.compile(r"(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)")

_RULE_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "RR-001": (">=", "Critical", "Temporarily hold transaction and require founder approval"),
    "RR-003": ("<", "Medium", "Flag pricing/cost review"),
    "RR-005": (">", "High", "Human approval required"),
    "RR-006": ("<", "Medium", "Ask for missing data or provide no-recommendation"),
    "RR-007": (">", "High", "Escalate operations plan and penalty exposure"),
}


def _coerce_threshold(rule_id: str, value: str) -> int | float:
    number = float(value)
    if rule_id in {"RR-001", "RR-005", "RR-007"}:
        return int(number)
    return number


def resolve_business_rules(
    rows: Sequence[Record], policy: PolicyConfig
) -> BusinessRuleSnapshot:
    row_map = {str(row.get("rule_id", "")): row for row in rows}
    policy_defaults: dict[str, int | float] = {
        "RR-001": policy.transaction_risk_threshold,
        "RR-003": policy.margin_threshold,
        "RR-005": policy.governance_amount_threshold_vnd,
        "RR-006": policy.credit_min_eligibility_score,
        "RR-007": policy.late_delivery_days_threshold,
    }
    applied: list[ResolvedRule] = []
    issues: list[ValidationIssue] = []

    for rule_id, (default_operator, default_severity, default_action) in _RULE_DEFAULTS.items():
        row = row_map.get(rule_id)
        condition = str(row.get("trigger_condition", "")) if row else ""
        match = _THRESHOLD_RE.search(condition)
        if row and match:
            operator = match.group(1)
            threshold = _coerce_threshold(rule_id, match.group(2))
            source = "13_RISK_RULES"
        else:
            operator = default_operator
            threshold = policy_defaults[rule_id]
            source = "policy_fallback"
            issues.append(
                ValidationIssue(
                    code="RISK_RULE_FALLBACK",
                    record_id=rule_id,
                    field="trigger_condition",
                    message=(
                        f"{rule_id} is missing or unparsable; policy fallback "
                        f"{operator} {threshold} is active."
                    ),
                )
            )
        applied.append(
            ResolvedRule(
                rule_id=rule_id,
                operator=operator,
                threshold=threshold,
                trigger_condition=condition or f"fallback {operator} {threshold}",
                severity=str(row.get("severity", default_severity)) if row else default_severity,
                required_action=(
                    str(row.get("required_action", default_action)) if row else default_action
                ),
                source=source,
            )
        )

    values = {rule.rule_id: rule.threshold for rule in applied}
    return BusinessRuleSnapshot(
        transaction_risk_threshold=int(values["RR-001"]),
        margin_threshold=float(values["RR-003"]),
        governance_amount_threshold_vnd=int(values["RR-005"]),
        credit_min_eligibility_score=float(values["RR-006"]),
        late_delivery_days_threshold=int(values["RR-007"]),
        applied_rules=applied,
        issues=issues,
    )


def get_resolved_rule(snapshot: BusinessRuleSnapshot, rule_id: str) -> ResolvedRule:
    return next(rule for rule in snapshot.applied_rules if rule.rule_id == rule_id)
