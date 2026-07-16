"""Read the published Team Pack without embedding spreadsheet row numbers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .contracts import PolicyConfig


DEFAULT_WORKBOOK = Path("data/MISTalent2026_OPC_AgenticAI_TeamPack_v2-1.xlsx")


def _python_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {column: _python_value(value) for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def load_team_pack(path: str | Path = DEFAULT_WORKBOOK) -> dict[str, list[dict[str, Any]]]:
    """Load all published sheets as record dictionaries keyed by actual sheet name."""

    workbook_path = Path(path)
    excel = pd.ExcelFile(workbook_path)
    return {
        sheet_name: _records(pd.read_excel(workbook_path, sheet_name=sheet_name))
        for sheet_name in excel.sheet_names
    }


def load_policy(path: str | Path = "config/policies.yaml") -> PolicyConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        return PolicyConfig.model_validate(yaml.safe_load(handle) or {})


def workbook_columns(team_pack: dict[str, list[dict[str, Any]]]) -> set[str]:
    """Return real column names; intentionally ignore stale dictionary sheet numbers."""

    columns: set[str] = set()
    for rows in team_pack.values():
        for row in rows[:1]:
            columns.update(row)
    return columns
