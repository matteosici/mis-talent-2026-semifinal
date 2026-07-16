"""Regenerate the frozen Finance/Risk samples from the published Team Pack."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from src.resolvers import build_finance_output  # noqa: E402
from src.team_pack import DEFAULT_WORKBOOK, load_policy, load_team_pack  # noqa: E402
from src.validation import build_risk_output  # noqa: E402


def main() -> None:
    team_pack = load_team_pack(ROOT / DEFAULT_WORKBOOK)
    policy = load_policy(ROOT / "config" / "policies.yaml")
    outputs = {
        "finance_output_sample.json": build_finance_output(
            team_pack, policy, DEFAULT_WORKBOOK.name
        ),
        "risk_output_sample.json": build_risk_output(
            team_pack, policy, DEFAULT_WORKBOOK.name
        ),
    }
    fixture_dir = ROOT / "fixtures"
    for filename, output in outputs.items():
        (fixture_dir / filename).write_text(
            output.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote fixtures/{filename}")


if __name__ == "__main__":
    main()
