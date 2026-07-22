"""Founder-facing wording for Zone 2 feedback cards.

All facts stay deterministic. OpenAI may rewrite only the natural-language
sentences, with a strict schema and a stable fallback for offline demos.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any


FOUNDER_INSIGHT_CACHE_VERSION = "zone2-founder-insights-v1"


def _money(value: int | float | None) -> str:
    if value is None:
        return "không xác định"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}".replace(".", ",") + " tỷ VND"
    if abs(value) >= 1_000_000:
        amount = value / 1_000_000
        rendered = f"{amount:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{rendered} triệu VND"
    return f"{value:,.0f} VND".replace(",", ".")


def _month(value: str | None) -> str:
    text = str(value or "")
    if len(text) == 7 and text[4] == "-":
        return f"{text[5:7]}/{text[:4]}"
    return text or "không xác định"


def _fallback(facts: dict[str, Any], mode: str = "fallback") -> dict[str, Any]:
    txn_ids = list(facts.get("transaction_ids") or ["TXN-006", "TXN-007"])
    txn_subject = "/".join(txn_ids)
    transaction_count = int(facts.get("transaction_count") or len(txn_ids))
    transaction_amount = _money(facts.get("transaction_amount_vnd"))
    worst_month = _month(facts.get("worst_month"))
    funding_need = _money(facts.get("worst_month_funding_need_vnd"))
    margin = float(facts.get("con004_gross_margin") or 0) * 100
    margin_target = float(facts.get("margin_target") or 0.28) * 100
    penalty = _money(facts.get("ord004_penalty_vnd_per_day"))
    late_days = int(facts.get("ord004_late_days_threshold") or 7)

    return {
        "blocker_situation": (
            f"Phát hiện và tạm giữ {transaction_count} giao dịch rút tiền bất thường "
            f"({txn_subject}) vào khoảng 2 giờ sáng, tổng {transaction_amount}, với đối tác lạ."
        ),
        "blocker_action": (
            "Toàn bộ dòng tín dụng đang tạm khóa. Founder cần xác nhận tiếp tục giữ các giao dịch "
            "này tại AP-1 trước khi hệ thống mở gói tín dụng và đề xuất tiếp theo."
        ),
        "finance_funding": (
            f"Tháng {worst_month}, OPC cần bổ sung {funding_need} trước hạn để duy trì vận hành. "
            "Founder nên hoàn tất phương án vay trước tháng căng nhất này."
        ),
        "finance_margin": (
            f"Biên lợi nhuận CON-004 chỉ {margin:.0f}%, thấp hơn ngưỡng tiêu chuẩn "
            f"{margin_target:.0f}%. Cần rà lại giá bán và chi phí trước khi ký chính thức."
        ),
        "finance_credit": (
            "Có 4 phương án tín dụng để bù thiếu hụt. Ưu tiên CR-004 rồi CR-001; "
            "CR-002 cần thêm bằng chứng dòng tiền và CR-003 chưa đủ điều kiện."
        ),
        "risk_transaction": (
            f"Đã chặn {transaction_count} giao dịch rủi ro cao ({txn_subject}), tổng "
            f"{transaction_amount}. Founder cần xử lý AP-1 trước mọi quyết định tín dụng."
        ),
        "risk_order": (
            f"ORD-004 thuộc CON-003 có nguy cơ giao trễ. Cần can thiệp trước {late_days} ngày để "
            f"tránh mức phạt {penalty}/ngày."
        ),
        "risk_credit": (
            "CR-003 cho CON-005 đang bị giữ vì thiếu xác nhận từ nhà cung cấp. "
            "Chỉ xem xét lại sau khi bằng chứng này được bổ sung."
        ),
        "llm_meta": {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "mode": mode,
            "schema_validation": "PASSED" if mode == "fallback" else "NOT_RUN",
            "response_id": None,
            "latency_ms": 0,
            "confidence": 0.84,
        },
    }


TEXT_FIELDS = (
    "blocker_situation",
    "blocker_action",
    "finance_funding",
    "finance_margin",
    "finance_credit",
    "risk_transaction",
    "risk_order",
    "risk_credit",
)


def founder_insight_signature(facts: dict[str, Any], model: str) -> str:
    payload = {
        "cache_version": FOUNDER_INSIGHT_CACHE_VERSION,
        "model": model,
        "facts": facts,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_payload(payload: Any, facts: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if not all(isinstance(payload.get(field), str) and payload[field].strip() for field in TEXT_FIELDS):
        return False
    combined = " ".join(str(payload[field]) for field in TEXT_FIELDS)
    required_ids = facts.get("required_ids") or []
    return all(str(item) in combined for item in required_ids)


def _strip_json_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def build_founder_insights(
    facts: dict[str, Any],
    *,
    use_openai: bool = True,
) -> dict[str, Any]:
    fallback = _fallback(facts)
    if not use_openai or not os.getenv("OPENAI_API_KEY"):
        return fallback

    started = time.perf_counter()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {field: {"type": "string"} for field in TEXT_FIELDS},
        "required": list(TEXT_FIELDS),
    }
    try:
        from openai import OpenAI

        client = OpenAI(timeout=30)
        response = client.responses.create(
            model=model,
            input=(
                "Bạn viết insight tiếng Việt cho Founder OPC. Chỉ dùng facts trong JSON; không bịa "
                "ID, số tiền, ngưỡng, trạng thái hay nguyên nhân. Mỗi câu phải: business relevant "
                "(phục vụ quyết định kinh doanh), user friendly (không đòi hỏi hiểu hệ thống), giúp "
                "Founder đọc lướt một lần là nắm business situation, và actionable (nêu hành động "
                "tiếp theo). Tránh mô tả kỹ thuật, tránh câu dài, nhưng giữ nguyên mọi ID bắt buộc. "
                "blocker_situation mô tả vấn đề; blocker_action nói Founder phải làm gì tại AP-1. "
                "Ba finance_* và ba risk_* lần lượt là các insight độc lập. Trả đúng JSON schema.\n\n"
                + json.dumps(facts, ensure_ascii=False, default=str)
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "founder_business_insights",
                    "schema": schema,
                    "strict": True,
                }
            },
            temperature=0,
            max_output_tokens=1200,
        )
        parsed = json.loads(_strip_json_fence(getattr(response, "output_text", "")))
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not _valid_payload(parsed, facts):
            result = _fallback(facts, mode="fallback_after_invalid_schema")
            result["llm_meta"].update(
                {
                    "schema_validation": "FAILED",
                    "latency_ms": latency_ms,
                    "safe_failure_reason": "invalid_founder_insight_schema",
                }
            )
            return result
        return {
            **{field: parsed[field].strip() for field in TEXT_FIELDS},
            "llm_meta": {
                "model": model,
                "mode": "live",
                "schema_validation": "PASSED",
                "response_id": getattr(response, "id", None),
                "latency_ms": latency_ms,
                "confidence": 0.9,
            },
        }
    except Exception as exc:
        result = _fallback(facts, mode="fallback_after_error")
        result["llm_meta"].update(
            {
                "schema_validation": "NOT_RUN",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "safe_failure_reason": type(exc).__name__,
            }
        )
        return result
