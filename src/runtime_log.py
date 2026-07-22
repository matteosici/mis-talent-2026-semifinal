"""Runtime log helpers for the MIS Talent prototype."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .decision_agent import DECISION_VERSION, TRACE_ID


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def event(
    *,
    agent_name: str,
    event_type: str,
    tool_or_api_id: str | None = None,
    request_id: str | None = None,
    masked_fields: list[str] | None = None,
    response_status: str | int | None = None,
    retry_count: int = 0,
    human_approval_id: str | None = None,
    safe_failure_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": _ts(),
        "trace_id": TRACE_ID,
        "agent_name": agent_name,
        "event_type": event_type,
        "tool_or_api_id": tool_or_api_id,
        "request_id": request_id,
        "masked_fields": masked_fields or [],
        "response_status": response_status,
        "retry_count": retry_count,
        "human_approval_id": human_approval_id,
        "decision_version": DECISION_VERSION,
        "safe_failure_reason": safe_failure_reason,
    }


def build_sample_runtime_log(decision_card: dict[str, Any]) -> list[dict[str, Any]]:
    llm_meta = decision_card.get("llm_meta", {})
    return [
        event(agent_name="Finance & Data Agent", event_type="observe", tool_or_api_id="TEAM_PACK_EXCEL", request_id="REQ-FIN-001", response_status="14_sheets_loaded_8_core_6_supporting"),
        event(agent_name="Risk & Compliance Agent", event_type="reason", tool_or_api_id="RR-001", request_id="REQ-RISK-001", masked_fields=["account_id", "counterparty_id"], response_status="critical_cluster_detected"),
        event(agent_name="Founder", event_type="approval", tool_or_api_id="AP-1", request_id="APR-001", masked_fields=["account_id", "counterparty_id"], response_status="approved_temporary_hold", human_approval_id="APR-001"),
        event(agent_name="Decision & Partner Agent", event_type="tool_call", tool_or_api_id="OPENAI_DECISION_CARD", request_id=llm_meta.get("response_id") or "REQ-LLM-FALLBACK", masked_fields=decision_card.get("masked_fields", []), response_status=llm_meta.get("mode", "unknown"), retry_count=0, safe_failure_reason=llm_meta.get("safe_failure_reason")),
        event(agent_name="Decision & Partner Agent", event_type="reflection", tool_or_api_id="SCHEMA_VALIDATION", request_id="REQ-DEC-001", masked_fields=decision_card.get("masked_fields", []), response_status=llm_meta.get("schema_validation", "NOT_RUN"), human_approval_id=decision_card.get("human_approval_id")),
    ]


def write_json(path: str | Path, payload: Any) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
