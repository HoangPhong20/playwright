"""Versioned crawler-output contract loaded by Databricks ETL."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import yaml


CONTRACT_PATH = Path(__file__).parents[1] / "contracts" / "agoda_hotel.yaml"
SUPPORTED_FORMATS = {
    "uri", "positive_price", "timestamp", "date", "rating_0_10",
    "non_negative_integer", "star_rating_0_5",
}
SUPPORTED_CROSS_FIELD_RULES = {"check_out_after_check_in"}


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    """Load and validate the small, versioned Agoda crawler contract."""
    with path.open(encoding="utf-8") as handle:
        contract = yaml.safe_load(handle)
    if not isinstance(contract, dict):
        raise ValueError("contract must be a YAML mapping")
    if not isinstance(contract.get("version"), str) or not contract["version"].strip():
        raise ValueError("contract must define a non-empty version")
    if contract.get("validation_layer") != "silver":
        raise ValueError("contract validation_layer must be 'silver'")
    fields = contract.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("contract must define fields")
    for name, definition in fields.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("contract field names must be lower snake_case")
        if not isinstance(definition, dict) or definition.get("type") != "string":
            raise ValueError(f"contract field {name!r} must have type string")
        if not isinstance(definition.get("required"), bool):
            raise ValueError(f"contract field {name!r} must declare required")
        format_name = definition.get("format")
        if format_name is not None and format_name not in SUPPORTED_FORMATS:
            raise ValueError(f"contract field {name!r} has an unsupported format")
    cross_field_rules = contract.get("cross_field_rules", [])
    if not isinstance(cross_field_rules, list) or any(
        rule not in SUPPORTED_CROSS_FIELD_RULES for rule in cross_field_rules
    ):
        raise ValueError("contract has an unsupported cross_field_rule")
    return contract


CONTRACT = load_contract()
CONTRACT_FIELDS = tuple(CONTRACT["fields"])
REQUIRED_FIELDS = tuple(
    name for name, definition in CONTRACT["fields"].items() if definition["required"]
)
