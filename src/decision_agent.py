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
) -> str:
    """Resolve the recommendation while giving an explicit human decision priority."""

    if final_state in _FINAL_STATE_REC:
        return _FINAL_STATE_REC[final_state]
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
        collateral_vnd, collateral_basis, demo_note = _resolve_collateral(
            product,
            mapping,
        )
        matrix.append({
            "credit_case_id": credit_case_id,
            "requested_amount_vnd": candidate.requested_amount_vnd if candidate else None,
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


def _fallback_openai_result(backend: DS1BackendOutput) -> OpenAIResult:
    finance = backend.finance.d5_handoff
    risk = backend.risk.d5_handoff
    txn_ids = risk.transaction_hold.txn_ids if risk.transaction_hold else []
    candidate_ids = list(finance.credit_candidate_ids or [])
    candidate_by_id = {
        item.credit_case_id: item for item in backend.finance.credit_candidates
    }
    package_ids = (
        list(backend.finance.credit_plan.decision_package_credit_case_ids)
        if backend.finance.credit_plan
        else candidate_ids
    )
    package_ids = [item for item in package_ids if item in candidate_ids]
    credit_conditions = [
        (
            f"AP-{index}: Founder phê duyệt hồ sơ {credit_case_id} trị giá "
            f"{_money(candidate_by_id[credit_case_id].requested_amount_vnd if credit_case_id in candidate_by_id else None)}."
        )
        for index, credit_case_id in enumerate(package_ids, start=2)
    ]
    credit_flag = next(iter(backend.risk.credit_risk_flags), None)
    conflicts = []
    if credit_flag:
        conflicts.append({
            "description": (
                f"Finance vẫn giữ {credit_flag.credit_case_id} trong danh sách candidate, "
                f"trong khi Risk flag {credit_flag.rule_id} vì eligibility "
                f"{credit_flag.eligibility_score:.2f} thấp hơn ngưỡng {credit_flag.threshold:.2f}."
            ),
            "resolution_note": (
                f"Giữ {credit_flag.credit_case_id} ở trạng thái có điều kiện, gắn uncertainty "
                "và yêu cầu Founder phê duyệt thay vì âm thầm loại bỏ."
            ),
        })
    return OpenAIResult(
        conflicts_detected=conflicts,
        conditions=[
            (
                "AP-1: Founder xác nhận tạm giữ "
                f"{('/'.join(txn_ids) if txn_ids else 'cụm giao dịch được Risk Agent flag')} "
                "trước mọi thao tác gửi hồ sơ tài chính."
            ),
            *credit_conditions,
            "AP-4: Founder phê duyệt gửi hồ sơ ra VietinBank sau khi dữ liệu đã được masking/tokenization.",
            "AP-5: Founder ra quyết định cuối cùng cho CON-004: nhận, từ chối hoặc đàm phán lại.",
        ],
        rationale=(
            "Nên khuyến nghị có điều kiện với CON-004 vì hợp đồng có thể tạo ra "
            "1.008B VND lợi nhuận gộp và giúp dòng tiền tháng 9 phục hồi, nhưng hệ thống "
            f"phải xử lý trước {_money(risk.transaction_hold_amount_vnd)} giao dịch đáng ngờ đang chờ tạm giữ, "
            f"phê duyệt {_money(finance.decision_package_total_ask_vnd)} gói tín dụng, đồng thời giữ CR-003 ở trạng thái tạm giữ cho tới khi có xác nhận nhà cung cấp."
        ),
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
    try:
        from openai import OpenAI
        client = OpenAI(timeout=30)
        prompt_payload = {
            "finance_handoff": backend.finance.d5_handoff.model_dump(mode="json"),
            "risk_handoff": backend.risk.d5_handoff.model_dump(mode="json"),
            "bank_fit_matrix": bank_fit_matrix,
        }
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            input=(
                "You are the Decision & Partner Agent for the OPC MIS Talent prototype. "
                "Use only structured data. Do not invent money figures, IDs, approvals, or customers. "
                "Return strict JSON with keys conflicts_detected, conditions, rationale.\n\n"
                + json.dumps(prompt_payload, ensure_ascii=False)
            ),
            temperature=0,
            max_output_tokens=1500,
        )
        parsed = json.loads(
            _strip_json_fence(getattr(response, "output_text", ""))
        )
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
            llm_meta={"model": os.getenv("OPENAI_MODEL", "gpt-4o"), "mode": "live", "confidence": 0.82, "response_id": getattr(response, "id", None), "latency_ms": latency_ms, "schema_validation": "PASSED"},
        )
    except Exception as exc:
        fallback = _fallback_openai_result(backend)
        return OpenAIResult(
            conflicts_detected=fallback.conflicts_detected,
            conditions=fallback.conditions,
            rationale=fallback.rationale,
            llm_meta={**fallback.llm_meta, "mode": "fallback_after_error", "schema_validation": "NOT_RUN", "safe_failure_reason": exc.__class__.__name__},
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
    candidate_by_id = {
        item.credit_case_id: item for item in backend.finance.credit_candidates
    }
    package_ids = (
        list(backend.finance.credit_plan.decision_package_credit_case_ids)
        if backend.finance.credit_plan
        else list(finance.credit_candidate_ids or [])
    )
    bank_fit_by_credit_id = {
        item["credit_case_id"]: item for item in bank_fit_matrix
    }
    financial_breakdown = []
    package_collateral_rows = []
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
    transaction_hold_subject = (
        "/".join(txn_ids) if txn_ids else "cụm giao dịch được Risk Agent flag"
    )
    ap5_status = (
        "approved"
        if final_state in {"ACTIVE", "REJECTED", "RENEGOTIATE"}
        else "pending"
    )
    approval_required = [
        {"id": "AP-1", "description": f"Tạm giữ {transaction_hold_subject}", "amount": risk.transaction_hold_amount_vnd, "status": ap1_status, "blocks": ["AP-2", "AP-3", "AP-4", "AP-5"]},
        {"id": "AP-2", "description": "Phê duyệt vốn lưu động CR-001", "amount": 950_000_000, "status": ap2_status, "blocks": ["AP-4", "AP-5"]},
        {"id": "AP-3", "description": "Phê duyệt bảo lãnh thực hiện CR-002", "amount": 420_000_000, "status": ap3_status, "blocks": ["AP-4", "AP-5"]},
        {"id": "AP-4", "description": "Phê duyệt gửi hồ sơ ngoài qua API-002", "amount": None, "status": ap4_status, "blocks": ["AP-5"]},
        {"id": "AP-5", "description": "Quyết định nhận/ký CON-004", "amount": 4_200_000_000, "status": ap5_status, "blocks": []},
    ]
    candidate_ids = set(finance.credit_candidate_ids or [])
    assessment_by_id = {
        item.credit_case_id: item for item in backend.risk.credit_assessments
    }
    evidence_missing_any = any(
        assessment_by_id[credit_case_id].evidence_missing
        for credit_case_id in candidate_ids
        if credit_case_id in assessment_by_id
    )
    recommendation = resolve_recommendation(
        final_state,
        any(item["status"] != "approved" for item in approval_required),
        evidence_missing_any,
    )
    return {
        "trace_id": TRACE_ID,
        "decision_version": DECISION_VERSION,
        "contract_id": "CON-004",
        "contract_name": "Cooperative Network Rollout - 20-Province Expansion",
        "customer_name_masked": "TOK-CUS-A91F",
        "state": final_state,
        "recommendation": recommendation,
        "financial_ask": {"breakdown": financial_breakdown, "total": finance.decision_package_total_ask_vnd, "collateral_total": sum(item["collateral_vnd"] for item in package_collateral_rows), "collateral_total_basis": collateral_total_basis, "cost_estimate_per_period": 67_000_000},
        "bank_fit_matrix": bank_fit_matrix,
        "risks_remaining": [{"description": "CR-002 eligibility 0.63 < 0.65", "rule_ref": "RR-006", "severity": "Medium"}, {"description": "ORD-004 có rủi ro triển khai; phạt 4.65 triệu VND/ngày nếu trễ quá 7 ngày", "rule_ref": "RR-007", "severity": "High"}],
        "missing_evidence": [{"description": "Thiếu xác nhận nhà cung cấp cho CR-003/CON-005", "blocks": ["CR-003"]}],
        "upside_if_conditions_met": {"gross_profit_vnd": 1_008_000_000, "recovery_month": "2026-09", "recovery_closing_cash_vnd": 350_000_000, "narrative": "OPC thoát vòng lặp thiếu dòng tiền; dòng tiền dự phóng chuyển dương từ tháng 9."},
        "approval_required": approval_required,
        "masked_fields": ["customer_id", "account_id", "contract_value", "access_token"],
        "human_approval_id": human_approval_id,
        "conflicts_detected": llm.conflicts_detected,
        "critical_flags": [] if ap1_status == "approved" else [f"{transaction_hold_subject} chưa được xác nhận tạm giữ"],
        "conditions": llm.conditions,
        "rationale": llm.rationale,
        "llm_meta": llm.llm_meta,
    }

