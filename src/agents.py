"""Runnable DS1 entrypoints mapped to D1 steps 3/4 and D5 handoffs."""

from __future__ import annotations

from pathlib import Path

from .contracts import DS1BackendOutput, FinanceOutput, RiskOutput
from .resolvers import build_finance_output
from .team_pack import DEFAULT_WORKBOOK, load_policy, load_team_pack
from .validation import build_risk_output


def run_d1_step3_finance_agent(
    workbook_path: str | Path = DEFAULT_WORKBOOK,
    policy_path: str | Path = "config/policies.yaml",
) -> FinanceOutput:
    team_pack = load_team_pack(workbook_path)
    policy = load_policy(policy_path)
    return build_finance_output(team_pack, policy, Path(workbook_path).name)


def run_d1_step4_risk_agent(
    workbook_path: str | Path = DEFAULT_WORKBOOK,
    policy_path: str | Path = "config/policies.yaml",
) -> RiskOutput:
    team_pack = load_team_pack(workbook_path)
    policy = load_policy(policy_path)
    return build_risk_output(team_pack, policy, Path(workbook_path).name)


def run_ds1_backend(
    workbook_path: str | Path = DEFAULT_WORKBOOK,
    policy_path: str | Path = "config/policies.yaml",
) -> DS1BackendOutput:
    team_pack = load_team_pack(workbook_path)
    policy = load_policy(policy_path)
    source_name = Path(workbook_path).name
    return DS1BackendOutput(
        finance=build_finance_output(team_pack, policy, source_name),
        risk=build_risk_output(team_pack, policy, source_name),
    )
