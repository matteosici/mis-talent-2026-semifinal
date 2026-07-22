"""Read the published Team Pack without embedding spreadsheet row numbers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .contracts import PolicyConfig, SourceAudit


DEFAULT_WORKBOOK = Path("data/MISTalent2026_OPC_AgenticAI_TeamPack_v2-1.xlsx")

DS1_CORE_SHEETS = (
    "04_CONTRACTS",
    "09_CASHFLOW",
    "07_INVOICES",
    "08_BANK_TXN",
    "13_RISK_RULES",
    "14_ALERTS",
    "10_CREDIT_PROFILE",
    "11_BANK_PRODUCTS",
)

# D1/D5 supporting evidence needed for joins, targets and safe handling.
DS1_SUPPORTING_SHEETS = (
    "02_OPC_PROFILE",
    "03_CUSTOMERS",
    "05_PRODUCTS",
    "06_ORDERS",
    "20_DATA_CLASS",
    "21_MASKING_EXAMPLES",
)

DS1_REQUIRED_SHEETS = DS1_CORE_SHEETS + DS1_SUPPORTING_SHEETS


def _python_value(value: Any, column: str | None = None) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if column and column.endswith("_date") and isinstance(value, (int, float)):
        return (
            pd.Timestamp("1899-12-30") + pd.to_timedelta(float(value), unit="D")
        ).date().isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {column: _python_value(value, column) for column, value in row.items()}
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


def audit_ds1_sources(
    team_pack: dict[str, list[dict[str, Any]]],
) -> SourceAudit:
    required = DS1_REQUIRED_SHEETS
    row_counts = {sheet: len(team_pack.get(sheet, [])) for sheet in required}
    missing = [sheet for sheet in required if sheet not in team_pack]
    return SourceAudit(
        row_counts=row_counts,
        loaded_sheets=[sheet for sheet in required if sheet in team_pack],
        missing_sheets=missing,
        core_complete=all(sheet in team_pack for sheet in DS1_CORE_SHEETS),
    )
