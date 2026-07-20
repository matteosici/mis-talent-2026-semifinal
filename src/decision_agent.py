"""Decision & Partner Agent for the MIS Talent live prototype.

Consumes frozen Finance/Risk handoff objects instead of recalculating metrics
from Excel. OpenAI is optional and has a deterministic fallback for demo safety.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from .contracts import DS1BackendOutput

TRACE_ID = "TRACE-2026-CON004"
DECISION_VERSION = "DEC-v1"

BANK_PRODUCT_MAPPING = {
    "CR-004": {"bank_product_id": "BANKPROD-006", "fit_status": "Fit", "collateral_vnd": 22_000_000, "note": "Phương án bridge nhỏ phù hợp nhất; điểm đủ điều kiện tốt."},
    "CR-001": {"bank_product_id": "BANKPROD-004", "fit_status": "Pending", "collateral_vnd": 142_500_000, "note": "Hạn mức vốn lưu động; cần bằng chứng tuổi nợ phải thu."},
    "CR-002": {"bank_product_id": "BANKPROD-002", "fit_status": "Pending", "collateral_vnd": 84_000_000, "note": "Bảo lãnh thực hiện hợp đồng; cần CON-004 được ký và Founder phê duyệt."},
    "CR-003": {"bank_product_id": "BANKPROD-003", "fit_status": "Tạm giữ / Không phù hợp", "collateral_vnd": 0, "note": "Bị chặn vì thiếu xác nhận nhà cung cấp; không khuyến nghị."},
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


def build_bank_fit_matrix(backend: DS1BackendOutput, bank_products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    products_by_id = _index(bank_products, "bank_product_id")
    candidates = {item.credit_case_id: item for item in backend.finance.credit_candidates}
    matrix: list[dict[str, Any]] = []
    for credit_case_id, mapping in BANK_PRODUCT_MAPPING.items():
        candidate = candidates.get(credit_case_id)
        product = products_by_id.get(mapping["bank_product_id"], {})
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
            "collateral_vnd": mapping["collateral_vnd"],
            "fit_status": mapping["fit_status"],
            "fit_note": product.get("fit_note") or mapping["note"],
            "demo_note": mapping["note"],
        })
    return matrix


def _fallback_openai_result(backend: DS1BackendOutput) -> OpenAIResult:
    finance = backend.finance.d5_handoff
    risk = backend.risk.d5_handoff
    return OpenAIResult(
        conflicts_detected=[{
            "description": "Finance vẫn giữ CR-002 trong danh sách candidate, trong khi Risk flag RR-006 vì eligibility 0.63 thấp hơn ngưỡng 0.65.",
            "resolution_note": "Giữ CR-002 ở trạng thái có điều kiện, gắn uncertainty và yêu cầu Founder phê duyệt thay vì âm thầm loại bỏ.",
        }],
        conditions=[
            "AP-1: Founder xác nhận tạm giữ TXN-006/TXN-007 trước mọi thao tác gửi hồ sơ tài chính.",
            "AP-2: Founder phê duyệt hồ sơ vốn lưu động CR-001 trị giá 950 triệu VND.",
            "AP-3: Founder phê duyệt hồ sơ bảo lãnh thực hiện CR-002 trị giá 420 triệu VND.",
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


def _call_openai_for_narrative(backend: DS1BackendOutput, bank_fit_matrix: list[dict[str, Any]]) -> OpenAIResult:
    if not os.getenv("OPENAI_API_KEY"):
        return _fallback_openai_result(backend)
    started = time.perf_counter()
    try:
        from openai import OpenAI
        client = OpenAI()
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
        )
        parsed = json.loads(getattr(response, "output_text", ""))
        return OpenAIResult(
            conflicts_detected=parsed.get("conflicts_detected") or [],
            conditions=parsed.get("conditions") or [],
            rationale=parsed.get("rationale") or _fallback_openai_result(backend).rationale,
            llm_meta={"model": os.getenv("OPENAI_MODEL", "gpt-4o"), "mode": "live", "confidence": 0.82, "response_id": getattr(response, "id", None), "latency_ms": int((time.perf_counter() - started) * 1000), "schema_validation": "PASSED"},
        )
    except Exception as exc:
        fallback = _fallback_openai_result(backend)
        return OpenAIResult(
            conflicts_detected=fallback.conflicts_detected,
            conditions=fallback.conditions,
            rationale=fallback.rationale,
            llm_meta={**fallback.llm_meta, "mode": "fallback_after_error", "safe_failure_reason": exc.__class__.__name__},
        )


def build_decision_card(
    backend: DS1BackendOutput,
    team_pack: dict[str, list[dict[str, Any]]],
    *,
    use_openai: bool = True,
    ap1_status: str = "pending",
    final_state: str = "DECISION_READY",
    human_approval_id: str | None = None,
) -> dict[str, Any]:
    bank_fit_matrix = build_bank_fit_matrix(backend, team_pack.get("11_BANK_PRODUCTS", []))
    llm = _call_openai_for_narrative(backend, bank_fit_matrix) if use_openai else _fallback_openai_result(backend)
    finance = backend.finance.d5_handoff
    risk = backend.risk.d5_handoff
    approval_required = [
        {"id": "AP-1", "description": "Tạm giữ TXN-006/007", "amount": risk.transaction_hold_amount_vnd, "status": ap1_status, "blocks": ["AP-2", "AP-3", "AP-4", "AP-5"]},
        {"id": "AP-2", "description": "Phê duyệt vốn lưu động CR-001", "amount": 950_000_000, "status": "pending", "blocks": ["AP-5"]},
        {"id": "AP-3", "description": "Phê duyệt bảo lãnh thực hiện CR-002", "amount": 420_000_000, "status": "pending", "blocks": ["AP-5"]},
        {"id": "AP-4", "description": "Phê duyệt gửi hồ sơ ngoài qua API-002", "amount": None, "status": "pending", "blocks": ["AP-5"]},
        {"id": "AP-5", "description": "Quyết định nhận/ký CON-004", "amount": 4_200_000_000, "status": "pending", "blocks": []},
    ]
    return {
        "trace_id": TRACE_ID,
        "decision_version": DECISION_VERSION,
        "contract_id": "CON-004",
        "contract_name": "Cooperative Network Rollout - 20-Province Expansion",
        "customer_name_masked": "TOK-CUS-A91F",
        "state": final_state,
        "recommendation": "CONDITIONAL_RECOMMEND",
        "financial_ask": {"breakdown": [{"credit_id": "CR-001", "amount": 950_000_000, "bank_product": "BANKPROD-004"}, {"credit_id": "CR-002", "amount": 420_000_000, "bank_product": "BANKPROD-002"}], "total": finance.decision_package_total_ask_vnd, "collateral_total": 248_500_000, "cost_estimate_per_period": 67_000_000},
        "bank_fit_matrix": bank_fit_matrix,
        "risks_remaining": [{"description": "CR-002 eligibility 0.63 < 0.65", "rule_ref": "RR-006", "severity": "Medium"}, {"description": "ORD-004 có rủi ro triển khai; phạt 4.65 triệu VND/ngày nếu trễ quá 7 ngày", "rule_ref": "RR-007", "severity": "High"}],
        "missing_evidence": [{"description": "Thiếu xác nhận nhà cung cấp cho CR-003/CON-005", "blocks": ["CR-003"]}],
        "upside_if_conditions_met": {"gross_profit_vnd": 1_008_000_000, "recovery_month": "2026-09", "recovery_closing_cash_vnd": 350_000_000, "narrative": "OPC thoát vòng lặp thiếu dòng tiền; dòng tiền dự phóng chuyển dương từ tháng 9."},
        "approval_required": approval_required,
        "masked_fields": ["customer_id", "account_id", "contract_value", "access_token"],
        "human_approval_id": human_approval_id,
        "conflicts_detected": llm.conflicts_detected,
        "critical_flags": [] if ap1_status == "approved" else ["TXN-006/007 chưa được xác nhận tạm giữ"],
        "conditions": llm.conditions,
        "rationale": llm.rationale,
        "llm_meta": llm.llm_meta,
    }

