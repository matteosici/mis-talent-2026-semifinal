"""Decision & Partner Agent for the MIS Talent live prototype.

Consumes frozen Finance/Risk handoff objects instead of recalculating metrics
from Excel. OpenAI is optional and has a deterministic fallback for demo safety.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any

from .contracts import DS1BackendOutput

TRACE_ID = "TRACE-2026-CON004"
DECISION_VERSION = "DEC-v1"

BANK_PRODUCT_MAPPING = {
    "CR-004": {"bank_product_id": "BANKPROD-006", "fit_status": "Fit", "prototype_collateral_vnd": 22_000_000, "note": "Phương án bridge nhỏ phù hợp nhất; điểm đủ điều kiện tốt."},
    "CR-001": {"bank_product_id": "BANKPROD-004", "fit_status": "Pending", "prototype_collateral_vnd": 142_500_000, "note": "Hạn mức vốn lưu động; cần bằng chứng tuổi nợ phải thu."},
    "CR-002": {"bank_product_id": "BANKPROD-002", "fit_status": "Pending", "prototype_collateral_vnd": 84_000_000, "note": "Bảo lãnh thực hiện hợp đồng; cần CON-004 được ký và Founder phê duyệt."},
    "CR-003": {"bank_product_id": "BANKPROD-003", "fit_status": "Tạm giữ / Không phù hợp", "prototype_collateral_vnd": 0, "note": "Bị chặn vì thiếu xác nhận nhà cung cấp; không khuyến nghị."},
}

PROTOTYPE_COLLATERAL_BASIS = (
    "prototype_fallback_not_provided_by_11_BANK_PRODUCTS"
)
SHEET_COLLATERAL_BASIS = "11_BANK_PRODUCTS.collateral_vnd"
MIXED_COLLATERAL_BASIS = "mixed_sheet_and_prototype_fallback"

# The BTC catalog has no dedicated working-capital endpoint for CR-001. The
# prototype therefore reuses API-002 for the two cases in the decision package,
# and records the mapping explicitly instead of implying a real bank submission.
CREDIT_TO_API = {
    "CR-001": "API-002",
    "CR-002": "API-002",
    "CR-003": "API-003",
    "CR-004": "API-005",
}

_MOCK_ERROR_CODE = {
    400: "validation_error",
    401: "auth_required",
    409: "state_conflict",
    422: "docs_incomplete",
    429: "rate_limited",
    503: "service_unavailable",
}

_MOCK_REQUIRED_HANDLING = {
    400: "Validate payload; do not submit until corrected.",
    401: "Refresh sandbox authentication; never expose credentials in logs.",
    409: "Refresh current application state before retrying.",
    422: "Request missing evidence and lower recommendation confidence.",
    429: "Use a bounded retry with backoff; keep the case pending.",
    503: "Fail safe and keep the case pending for a later retry.",
}

_FINAL_STATE_REC = {
    "ACTIVE": "RECOMMEND",
    "REJECTED": "NOT_RECOMMEND",
    "RENEGOTIATE": "CONDITIONAL_RECOMMEND",
    "NEED_MORE_INFORMATION": "NEEDS_INFO",
}


@dataclass(frozen=True)
class OpenAIResult:
    conflicts_detected: list[dict[str, str]]
    conditions: list[str]
    rationale: str
    llm_meta: dict[str, Any]


def _money(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B VND"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.0f}M VND"
    return f"{value:,.0f} VND"


def _index(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row.get(key)): row for row in rows if row.get(key) is not None}


def _possible_statuses(value: Any) -> list[int]:
    statuses: list[int] = []
    for item in str(value or "").split(","):
        try:
            statuses.append(int(item.strip()))
        except ValueError:
            continue
    return statuses


def resolve_recommendation(
    final_state: str,
    has_pending_approvals: bool,
    evidence_missing: bool,
    has_rejected_approvals: bool = False,
) -> str:
    """Resolve the recommendation while giving an explicit human decision priority."""

    if final_state in _FINAL_STATE_REC:
        return _FINAL_STATE_REC[final_state]
    if has_rejected_approvals:
        return "NOT_RECOMMEND"
    if evidence_missing:
        return "NOT_RECOMMEND"
    if has_pending_approvals:
        return "CONDITIONAL_RECOMMEND"
    return "RECOMMEND"


def call_bank_api_mock(
    credit_case_id: str,
    amount_vnd: int,
    simulate_status: int = 200,
    *,
    api_catalog: list[dict[str, Any]] | None = None,
    sandbox_contracts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Simulate a BTC bank pre-check without making any external request.

    The response is deliberately structured like a runtime-safe adapter: an
    unknown mapping, invalid amount, or forced error becomes a visible failure
    result instead of an exception or a fabricated bank approval.
    """

    api_id = CREDIT_TO_API.get(str(credit_case_id))
    catalog_row = _index(api_catalog or [], "api_id").get(str(api_id), {})
    contract_row = _index(sandbox_contracts or [], "api_id").get(str(api_id), {})
    try:
        requested_status = int(simulate_status)
    except (TypeError, ValueError):
        requested_status = 400
    declared_statuses = _possible_statuses(contract_row.get("possible_status"))

    if api_id is None:
        return {
            "mode": "mock",
            "submitted_to_real_bank": False,
            "ok": False,
            "credit_case_id": str(credit_case_id),
            "api_id": None,
            "http_status": 400,
            "error_code": "credit_api_mapping_not_found",
            "safe_failure_reason": "No BTC API mapping exists for this credit case.",
            "required_handling": "Keep the case pending and request a reviewed mapping.",
        }

    if amount_vnd <= 0:
        requested_status = 400

    status_supported = not declared_statuses or requested_status in declared_statuses
    base = {
        "mode": "mock",
        "submitted_to_real_bank": False,
        "credit_case_id": str(credit_case_id),
        "amount_vnd": int(amount_vnd),
        "api_id": api_id,
        "provider": catalog_row.get("provider", "BTC Sandbox"),
        "method": catalog_row.get("method", "POST"),
        "endpoint": catalog_row.get("endpoint", contract_row.get("endpoint")),
        "requires_human_approval": contract_row.get("requires_human_approval"),
        "contract_required_handling": contract_row.get("required_handling"),
        "http_status": requested_status,
        "contract_status_supported": status_supported,
        "declared_statuses": declared_statuses,
        "masked_fields": [
            field.strip()
            for field in str(contract_row.get("sensitive_fields") or "").split(",")
            if field.strip()
        ],
    }
    if requested_status == 200:
        return {
            **base,
            "ok": True,
            "result": "precheck_received",
            "message": "Sandbox pre-check completed; human approval is still required before submission.",
        }

    error_code = _MOCK_ERROR_CODE.get(requested_status, "sandbox_error")
    return {
        **base,
        "ok": False,
        "error_code": error_code,
        "safe_failure_reason": (
            f"Forced sandbox response {requested_status} ({error_code})."
            if status_supported
            else f"Status {requested_status} is not declared for {api_id}; treated as an injected transport failure."
        ),
        "required_handling": _MOCK_REQUIRED_HANDLING.get(
            requested_status,
            str(contract_row.get("required_handling") or "Keep the case pending for review."),
        ),
    }


def _resolve_collateral(
    product: dict[str, Any],
    mapping: dict[str, Any],
) -> tuple[int | float, str, str]:
    """Prefer absolute collateral from the product sheet, then fail transparently."""

    raw_value = product.get("collateral_vnd")
    if raw_value is not None and not isinstance(raw_value, bool):
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            numeric_value = math.nan
        if math.isfinite(numeric_value) and numeric_value >= 0:
            collateral_vnd: int | float = (
                int(numeric_value) if numeric_value.is_integer() else numeric_value
            )
            return (
                collateral_vnd,
                SHEET_COLLATERAL_BASIS,
                "Read from 11_BANK_PRODUCTS.collateral_vnd. " + mapping["note"],
            )

    return (
        mapping["prototype_collateral_vnd"],
        PROTOTYPE_COLLATERAL_BASIS,
        "Prototype fallback: 11_BANK_PRODUCTS does not provide a valid "
        "absolute collateral_vnd amount. " + mapping["note"],
    )


def build_bank_fit_matrix(backend: DS1BackendOutput, bank_products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    products_by_id = _index(bank_products, "bank_product_id")
    candidates = {item.credit_case_id: item for item in backend.finance.credit_candidates}
    matrix: list[dict[str, Any]] = []
    for credit_case_id, mapping in BANK_PRODUCT_MAPPING.items():
        candidate = candidates.get(credit_case_id)
        product = products_by_id.get(mapping["bank_product_id"], {})
        requested_amount = candidate.requested_amount_vnd if candidate else None
        collateral_vnd, collateral_basis, demo_note = _resolve_collateral(product, mapping)
        matrix.append({
            "credit_case_id": credit_case_id,
            "requested_amount_vnd": requested_amount,
            "eligibility_score": candidate.eligibility_score if candidate else None,
            "candidate_status": candidate.candidate_status if candidate else "hold",
            "bank_product_id": mapping["bank_product_id"],
            "bank": product.get("bank", "Sandbox Bank"),
            "product_name": product.get("product_name", mapping["bank_product_id"]),
            "annual_rate_or_fee": product.get("annual_rate_or_fee"),
            "processing_fee_rate": product.get("processing_fee_rate"),
            "collateral_ratio": product.get("collateral_ratio"),
            "collateral_vnd": collateral_vnd,
            "collateral_basis": collateral_basis,
            "fit_status": mapping["fit_status"],
            "fit_note": product.get("fit_note") or mapping["note"],
            "demo_note": demo_note,
        })
    return matrix


def _candidate_by_id(backend: DS1BackendOutput, credit_case_id: str):
    return next(
        (
            item
            for item in backend.finance.credit_candidates
            if item.credit_case_id == credit_case_id
        ),
        None,
    )


def _con004_margin(backend: DS1BackendOutput):
    return next(
        (
            item
            for item in backend.finance.margin_analysis
            if item.contract_id == "CON-004"
        ),
        None,
    )


def _recovery_cashflow(backend: DS1BackendOutput):
    positive_month = next(
        (
            month
            for month in backend.finance.cashflow.months
            if month.closing_cash_vnd > 0
        ),
        None,
    )
    return positive_month or backend.finance.cashflow.months[-1]


def _safe_customer_token(backend: DS1BackendOutput) -> str:
    note = next(
        (
            item
            for item in backend.risk.safe_handling_notes
            if item.field_name == "customer_id"
        ),
        None,
    )
    return (note.tokenized_value or note.masked_value) if note else "[REDACTED]"


def _decision_breakdown(
    backend: DS1BackendOutput,
    bank_fit_matrix: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    plan = backend.finance.credit_plan
    product_by_credit = {
        item["credit_case_id"]: item["bank_product_id"] for item in bank_fit_matrix
    }
    candidates = {
        item.credit_case_id: item for item in backend.finance.credit_candidates
    }
    if plan is None:
        return []
    breakdown = []
    for credit_id in plan.decision_package_credit_case_ids:
        candidate = candidates.get(credit_id)
        if candidate is None:
            continue
        breakdown.append(
            {
                "credit_id": credit_id,
                "amount": candidate.requested_amount_vnd,
                "bank_product": product_by_credit.get(credit_id),
            }
        )
    return breakdown


def _approval_amounts(backend: DS1BackendOutput) -> dict[str, int]:
    return {
        item.credit_case_id: item.requested_amount_vnd
        for item in backend.finance.credit_candidates
    }


def _risks_remaining(backend: DS1BackendOutput) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for flag in backend.risk.credit_risk_flags:
        risks.append(
            {
                "description": (
                    f"{flag.credit_case_id} eligibility {flag.eligibility_score:g} "
                    f"< {flag.threshold:g}"
                ),
                "rule_ref": flag.rule_id,
                "severity": "Medium" if flag.disposition == "borderline" else "High",
            }
        )
    for item in backend.risk.execution_risks:
        risks.append(
            {
                "description": (
                    f"{item.order_id} {item.status}; phạt "
                    f"{_money(item.potential_penalty_vnd_per_day)}/ngày nếu trễ "
                    f"quá {item.late_delivery_days_threshold} ngày"
                ),
                "rule_ref": item.rule_id,
                "severity": "High" if item.systemic else "Medium",
            }
        )
    return risks


def _missing_evidence(backend: DS1BackendOutput) -> list[dict[str, Any]]:
    missing = []
    for candidate in backend.finance.credit_candidates:
        if candidate.evidence_missing:
            missing.append(
                {
                    "description": (
                        f"Thiếu bằng chứng cho {candidate.credit_case_id}: "
                        f"{candidate.precheck_note}"
                    ),
                    "blocks": [candidate.credit_case_id],
                }
            )
    return missing


def _fallback_openai_result(backend: DS1BackendOutput) -> OpenAIResult:
    finance = backend.finance.d5_handoff
    risk = backend.risk.d5_handoff
    if finance is None or risk is None:
        raise ValueError("Finance/Risk handoff is required before Decision Agent synthesis.")

    txn_ids = risk.transaction_hold.txn_ids if risk.transaction_hold else []
    candidate_by_id = {item.credit_case_id: item for item in backend.finance.credit_candidates}
    package_ids = (
        list(backend.finance.credit_plan.decision_package_credit_case_ids)
        if backend.finance.credit_plan
        else list(finance.credit_candidate_ids or [])
    )
    package_ids = [item for item in package_ids if item in candidate_by_id]
    credit_conditions = [
        (
            f"AP-{index}: Founder cân nhắc phê duyệt {credit_case_id} "
            f"({_money(candidate_by_id[credit_case_id].requested_amount_vnd)}) nếu bằng chứng đã đủ."
        )
        for index, credit_case_id in enumerate(package_ids, start=2)
    ]

    borderline = next(
        (
            item
            for item in backend.risk.credit_risk_flags
            if item.disposition == "borderline"
        ),
        next(iter(backend.risk.credit_risk_flags), None),
    )
    conflicts = []
    if borderline:
        conflicts.append({
            "description": (
                f"Finance vẫn giữ {borderline.credit_case_id} trong danh sách candidate, "
                f"nhưng Risk flag {borderline.rule_id} vì eligibility "
                f"{borderline.eligibility_score:g} thấp hơn ngưỡng {borderline.threshold:g}."
            ),
            "resolution_note": (
                "Giữ ở trạng thái có điều kiện, hiển thị uncertainty và yêu cầu Founder quyết định thay vì tự loại bỏ."
            ),
        })
    else:
        conflicts.append({
            "description": "Không phát hiện mâu thuẫn trọng yếu giữa Finance và Risk.",
            "resolution_note": "Tiếp tục dùng structured handoff và giữ approval gate bắt buộc.",
        })

    con004 = _con004_margin(backend)
    rationale = (
        "Việc cần làm tiếp cho Founder: xử lý AP-1 trước để đóng băng cụm giao dịch rủi ro, "
        f"sau đó duyệt tuần tự gói tín dụng {_money(finance.decision_package_total_ask_vnd)}. "
        "Nếu các điều kiện này hoàn tất, CON-004 đáng tiếp tục vì upside ước tính "
        f"{_money((con004.gross_profit_vnd if con004 else None))}; nếu thiếu bằng chứng hoặc AP nào chưa xong, "
        "không chuyển hồ sơ sang Active."
    )
    return OpenAIResult(
        conflicts_detected=conflicts,
        conditions=[
            (
                "AP-1: Founder xác nhận tạm giữ "
                f"{('/'.join(txn_ids) if txn_ids else 'cụm giao dịch RR-001')} "
                "trước mọi thao tác gửi hồ sơ tài chính."
            ),
            *credit_conditions,
            "AP-4: Founder phê duyệt gửi hồ sơ ra đối tác sau khi dữ liệu đã được masking/tokenization.",
            "AP-5: Founder ra quyết định cuối cùng cho CON-004: nhận, từ chối hoặc đàm phán lại.",
        ],
        rationale=rationale,
        llm_meta={"model": os.getenv("OPENAI_MODEL", "gpt-4o"), "mode": "fallback", "confidence": 0.78, "response_id": None, "latency_ms": 0, "schema_validation": "PASSED"},
    )


def _validate_narrative(
    conflicts: Any,
    conditions: Any,
    rationale: Any,
) -> bool:
    """Validate the minimum Decision Card narrative contract."""

    if not isinstance(conflicts, list) or not all(
        isinstance(conflict, dict) for conflict in conflicts
    ):
        return False
    if not isinstance(conditions, list) or not all(
        isinstance(condition, str) for condition in conditions
    ):
        return False
    return isinstance(rationale, str) and bool(rationale.strip())


def _strip_json_fence(value: str) -> str:
    """Remove an optional Markdown JSON fence without altering plain JSON."""

    text = value.strip()
    lines = text.splitlines()
    if lines and lines[0].strip().lower() in {"```", "```json"}:
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _call_openai_for_narrative(backend: DS1BackendOutput, bank_fit_matrix: list[dict[str, Any]]) -> OpenAIResult:
    if not os.getenv("OPENAI_API_KEY"):
        return _fallback_openai_result(backend)

    started = time.perf_counter()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    try:
        from openai import OpenAI

        client = OpenAI(timeout=30)
        prompt_payload = {
            "finance_handoff": backend.finance.d5_handoff.model_dump(mode="json"),
            "risk_handoff": backend.risk.d5_handoff.model_dump(mode="json"),
            "bank_fit_matrix": bank_fit_matrix,
        }
        narrative_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "conflicts_detected": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "description": {"type": "string"},
                            "resolution_note": {"type": "string"},
                        },
                        "required": ["description", "resolution_note"],
                    },
                },
                "conditions": {"type": "array", "items": {"type": "string"}},
                "rationale": {"type": "string"},
            },
            "required": ["conflicts_detected", "conditions", "rationale"],
        }
        response = client.responses.create(
            model=model,
            input=(
                "You are the Decision & Partner Agent for the OPC MIS Talent prototype. "
                "Use only structured data. Do not invent money figures, IDs, approvals, or customers. "
                "Return Vietnamese JSON that follows the provided schema exactly. "
                "conflicts_detected must contain objects with description and resolution_note. "
                "conditions must be concise action conditions. rationale must be one concise paragraph.\n\n"
                + json.dumps(prompt_payload, ensure_ascii=False)
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "decision_narrative",
                    "schema": narrative_schema,
                    "strict": True,
                }
            },
            temperature=0,
            max_output_tokens=1000,
        )
        parsed = json.loads(_strip_json_fence(getattr(response, "output_text", "")))
        conflicts = parsed.get("conflicts_detected") if isinstance(parsed, dict) else None
        conditions = parsed.get("conditions") if isinstance(parsed, dict) else None
        rationale = parsed.get("rationale") if isinstance(parsed, dict) else None
        latency_ms = int((time.perf_counter() - started) * 1000)

        if not _validate_narrative(conflicts, conditions, rationale):
            fallback = _fallback_openai_result(backend)
            return OpenAIResult(
                conflicts_detected=fallback.conflicts_detected,
                conditions=fallback.conditions,
                rationale=fallback.rationale,
                llm_meta={
                    **fallback.llm_meta,
                    "model": model,
                    "mode": "fallback_after_invalid_schema",
                    "response_id": getattr(response, "id", None),
                    "latency_ms": latency_ms,
                    "schema_validation": "FAILED",
                    "safe_failure_reason": "invalid_narrative_schema",
                },
            )

        return OpenAIResult(
            conflicts_detected=conflicts,
            conditions=conditions,
            rationale=rationale,
            llm_meta={
                "model": model,
                "mode": "live",
                "confidence": 0.82,
                "response_id": getattr(response, "id", None),
                "latency_ms": latency_ms,
                "schema_validation": "PASSED",
            },
        )
    except Exception as exc:  # pragma: no cover - depends on external API/network
        fallback = _fallback_openai_result(backend)
        return OpenAIResult(
            conflicts_detected=fallback.conflicts_detected,
            conditions=fallback.conditions,
            rationale=fallback.rationale,
            llm_meta={
                **fallback.llm_meta,
                "model": model,
                "mode": "fallback_after_error",
                "schema_validation": "NOT_RUN",
                "safe_failure_reason": exc.__class__.__name__,
            },
        )

def build_decision_card(
    backend: DS1BackendOutput,
    team_pack: dict[str, list[dict[str, Any]]],
    *,
    use_openai: bool = True,
    ap1_status: str = "pending",
    ap2_status: str = "pending",
    ap3_status: str = "pending",
    ap4_status: str = "pending",
    final_state: str = "DECISION_READY",
    human_approval_id: str | None = None,
) -> dict[str, Any]:
    bank_fit_matrix = build_bank_fit_matrix(backend, team_pack.get("11_BANK_PRODUCTS", []))
    llm = _call_openai_for_narrative(backend, bank_fit_matrix) if use_openai else _fallback_openai_result(backend)
    finance = backend.finance.d5_handoff
    risk = backend.risk.d5_handoff
    if finance is None or risk is None:
        raise ValueError("Finance/Risk handoff is required before Decision Agent synthesis.")

    candidate_by_id = {item.credit_case_id: item for item in backend.finance.credit_candidates}
    package_ids = (
        list(backend.finance.credit_plan.decision_package_credit_case_ids)
        if backend.finance.credit_plan
        else list(finance.credit_candidate_ids or [])
    )
    bank_fit_by_credit_id = {item["credit_case_id"]: item for item in bank_fit_matrix}
    financial_breakdown: list[dict[str, Any]] = []
    package_collateral_rows: list[dict[str, Any]] = []
    for credit_case_id in package_ids:
        candidate = candidate_by_id.get(credit_case_id)
        fit = bank_fit_by_credit_id.get(credit_case_id, {})
        financial_breakdown.append({
            "credit_id": credit_case_id,
            "amount": candidate.requested_amount_vnd if candidate else None,
            "bank_product": fit.get("bank_product_id"),
        })
        if fit.get("collateral_vnd") is not None:
            package_collateral_rows.append(fit)
    collateral_bases = {
        str(item["collateral_basis"])
        for item in package_collateral_rows
        if item.get("collateral_basis")
    }
    collateral_total_basis = (
        next(iter(collateral_bases))
        if len(collateral_bases) == 1
        else MIXED_COLLATERAL_BASIS
        if collateral_bases
        else None
    )

    txn_ids = risk.transaction_hold.txn_ids if risk.transaction_hold else []
    transaction_hold_subject = "/".join(txn_ids) if txn_ids else "cụm giao dịch RR-001"
    con004 = _con004_margin(backend)
    recovery = _recovery_cashflow(backend)
    ap5_status = {
        "ACTIVE": "approved",
        "REJECTED": "rejected",
        "NEED_MORE_INFORMATION": "need_more_information",
        "RENEGOTIATE": "renegotiate",
    }.get(final_state, "pending")
    approval_required = [
        {"id": "AP-1", "description": f"Tạm giữ {transaction_hold_subject}", "amount": risk.transaction_hold_amount_vnd, "status": ap1_status, "blocks": ["AP-2", "AP-3", "AP-4", "AP-5"]},
        {"id": "AP-2", "description": "Phê duyệt vốn lưu động CR-001", "amount": candidate_by_id.get("CR-001").requested_amount_vnd if candidate_by_id.get("CR-001") else 0, "status": ap2_status, "blocks": ["AP-4", "AP-5"]},
        {"id": "AP-3", "description": "Phê duyệt bảo lãnh thực hiện CR-002", "amount": candidate_by_id.get("CR-002").requested_amount_vnd if candidate_by_id.get("CR-002") else 0, "status": ap3_status, "blocks": ["AP-4", "AP-5"]},
        {"id": "AP-4", "description": "Phê duyệt gửi hồ sơ ngoài qua API-002", "amount": None, "status": ap4_status, "blocks": ["AP-5"]},
        {"id": "AP-5", "description": "Quyết định nhận/ký CON-004", "amount": next((item.contract_value_vnd for item in backend.finance.margin_analysis if item.contract_id == "CON-004"), None), "status": ap5_status, "blocks": []},
    ]
    candidate_ids = set(finance.credit_candidate_ids or [])
    assessment_by_id = {item.credit_case_id: item for item in backend.risk.credit_assessments}
    evidence_missing_any = any(
        assessment_by_id[credit_case_id].evidence_missing
        for credit_case_id in candidate_ids
        if credit_case_id in assessment_by_id
    )
    recommendation = resolve_recommendation(
        final_state,
        any(item["status"] == "pending" for item in approval_required),
        evidence_missing_any,
        any(item["status"] == "rejected" for item in approval_required),
    )
    return {
        "trace_id": TRACE_ID,
        "decision_version": DECISION_VERSION,
        "contract_id": "CON-004",
        "contract_name": "Cooperative Network Rollout - 20-Province Expansion",
        "customer_name_masked": _safe_customer_token(backend),
        "state": final_state,
        "recommendation": recommendation,
        "financial_ask": {"breakdown": financial_breakdown, "total": finance.decision_package_total_ask_vnd, "collateral_total": sum(item["collateral_vnd"] for item in package_collateral_rows), "collateral_total_basis": collateral_total_basis, "cost_estimate_per_period": 67_000_000},
        "bank_fit_matrix": bank_fit_matrix,
        "risks_remaining": _risks_remaining(backend),
        "missing_evidence": _missing_evidence(backend),
        "upside_if_conditions_met": {"gross_profit_vnd": None if con004 is None else con004.gross_profit_vnd, "recovery_month": recovery.month, "recovery_closing_cash_vnd": recovery.closing_cash_vnd, "narrative": "OPC thoát vòng lặp thiếu dòng tiền nếu các điều kiện phê duyệt được xử lý đúng thứ tự."},
        "approval_required": approval_required,
        "masked_fields": ["customer_id", "account_id", "contract_value", "access_token"],
        "human_approval_id": human_approval_id,
        "conflicts_detected": llm.conflicts_detected,
        "critical_flags": [] if ap1_status == "approved" else [f"{transaction_hold_subject} chưa được xác nhận tạm giữ"],
        "conditions": llm.conditions,
        "rationale": llm.rationale,
        "llm_meta": llm.llm_meta,
    }


