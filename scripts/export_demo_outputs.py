from __future__ import annotations

from pathlib import Path
import os
import sys

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents import run_ds1_backend
from src.decision_agent import build_decision_card
from src.runtime_log import build_sample_runtime_log, write_json
from src.team_pack import DEFAULT_WORKBOOK, load_team_pack

WORKBOOK = ROOT / DEFAULT_WORKBOOK
POLICY = ROOT / "config" / "policies.yaml"


def main() -> None:
    team_pack = load_team_pack(WORKBOOK)
    backend = run_ds1_backend(WORKBOOK, POLICY)
    decision_card = build_decision_card(
        backend,
        team_pack,
        use_openai=bool(os.getenv("OPENAI_API_KEY")),
        ap1_status="approved",
        final_state="DECISION_READY",
        human_approval_id="APR-001",
    )
    write_json(
        ROOT / "output" / "demo_backend_output.json",
        {
            "finance_handoff": backend.finance.d5_handoff.model_dump(mode="json"),
            "risk_handoff": backend.risk.d5_handoff.model_dump(mode="json"),
            "finance_source_audit": backend.finance.source_audit.model_dump(mode="json") if backend.finance.source_audit else None,
            "risk_rule_snapshot": backend.risk.rule_snapshot.model_dump(mode="json") if backend.risk.rule_snapshot else None,
        },
    )
    write_json(ROOT / "output" / "demo_decision_card.json", decision_card)
    write_json(ROOT / "runtime_logs" / "sample_runtime_log.json", build_sample_runtime_log(decision_card))
    print("Exported output/demo_backend_output.json")
    print("Exported output/demo_decision_card.json")
    print("Exported runtime_logs/sample_runtime_log.json")


if __name__ == "__main__":
    main()




