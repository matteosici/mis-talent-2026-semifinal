"""D5 safe-handling helpers for restricted identifiers and financial values."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import SafeHandlingNote


Record = Mapping[str, Any]

_TOKEN_PREFIX = {
    "customer_id": "CUS",
    "account_id": "ACC",
    "counterparty_id": "CP",
    "company_id": "ORG",
}


def _stable_token(field_name: str, value: str) -> str:
    prefix = _TOKEN_PREFIX.get(field_name, "ID")
    digest = hashlib.sha256(f"{field_name}:{value}".encode("utf-8")).hexdigest()[:4].upper()
    return f"TOK-{prefix}-{digest}"


def _mask_identifier(value: str) -> str:
    if "_" in value:
        head = value.split("_", 1)[0]
        return f"{head}_****"
    if "-" in value:
        head = value.split("-", 1)[0]
        return f"{head}-***{value[-3:]}"
    return f"***{value[-3:]}" if len(value) >= 3 else "***"


def _classification_for(field_name: str, rows: Sequence[Record]) -> tuple[str, str]:
    for row in rows:
        fields = {part.strip() for part in str(row.get("example_field", "")).split(",")}
        if field_name in fields:
            handling_rule = str(
                row.get("masking_or_tokenization", "Review required")
            )
            # Metadata examples can themselves resemble a real identifier. Keep the
            # instruction, but never echo an example value into the agent payload.
            handling_rule = handling_rule.split("; e.g.", maxsplit=1)[0]
            return str(row.get("classification", "unknown")), handling_rule
    return "unknown", "Review required"


def safe_handle_value(
    field_name: str,
    raw_value: Any,
    data_class_rows: Sequence[Record],
    masking_examples: Sequence[Record],
) -> SafeHandlingNote:
    raw_text = "" if raw_value is None else str(raw_value)
    classification, handling_rule = _classification_for(field_name, data_class_rows)
    example = next(
        (
            row
            for row in masking_examples
            if str(row.get("source_field", "")) == field_name
            and str(row.get("raw_example", "")) == raw_text
        ),
        None,
    )

    if example:
        masked = example.get("masked_example")
        tokenized = example.get("tokenized_example")
        return SafeHandlingNote(
            field_name=field_name,
            classification=classification,
            handling_rule=handling_rule,
            masked_value=None if masked is None else str(masked),
            tokenized_value=None if tokenized is None else str(tokenized),
        )

    if field_name == "contract_value":
        amount = int(float(raw_value or 0))
        masked_value = f"{amount / 1_000_000_000:.1f}B band"
        tokenized_value = None
    elif field_name in _TOKEN_PREFIX:
        masked_value = _mask_identifier(raw_text)
        tokenized_value = _stable_token(field_name, raw_text)
    elif field_name in {"access_token", "api_key"}:
        masked_value = "[SECRET]"
        tokenized_value = "vault://sandbox/token"
    else:
        masked_value = "[REDACTED]"
        tokenized_value = None

    return SafeHandlingNote(
        field_name=field_name,
        classification=classification,
        handling_rule=handling_rule,
        masked_value=masked_value,
        tokenized_value=tokenized_value,
    )


def build_safe_handling_notes(
    values: Mapping[str, Any],
    data_class_rows: Sequence[Record],
    masking_examples: Sequence[Record],
) -> list[SafeHandlingNote]:
    return [
        safe_handle_value(field_name, value, data_class_rows, masking_examples)
        for field_name, value in values.items()
    ]
