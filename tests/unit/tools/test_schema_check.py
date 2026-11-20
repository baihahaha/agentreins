"""Built-in basic argument check for sources that cannot validate."""

import pytest
from pydantic import JsonValue

from agentreins.tools.schema_check import check_arguments

SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "sku": {"type": "string"},
        "qty": {"type": "integer"},
        "price": {"type": "number"},
        "rush": {"type": "boolean"},
        "mode": {"enum": ["air", "sea"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "note": {"type": ["string", "null"]},
        "address": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        "anything": {"format": "made-up", "type": "weird"},
    },
    "required": ["sku"],
    "additionalProperties": False,
}


def test_valid_arguments_pass() -> None:
    args: dict[str, JsonValue] = {
        "sku": "W1",
        "qty": 2,
        "price": 1.5,
        "rush": True,
        "mode": "sea",
        "tags": ["a"],
        "note": None,
        "address": {"city": "Oslo"},
        "anything": 123,
    }
    assert check_arguments(SCHEMA, args) is None
    assert check_arguments(SCHEMA, {"sku": "W1", "qty": 2.0}) is None  # 2.0 is an integer in JSON


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        ({}, "arguments.sku is required"),
        ({"sku": 1}, "arguments.sku must be string"),
        ({"sku": "W1", "qty": True}, "arguments.qty must be integer"),
        ({"sku": "W1", "qty": 1.5}, "arguments.qty must be integer"),
        ({"sku": "W1", "price": "1"}, "arguments.price must be number"),
        ({"sku": "W1", "mode": "rail"}, "arguments.mode must be one of ['air', 'sea']"),
        ({"sku": "W1", "tags": ["a", 2]}, "arguments.tags[1] must be string"),
        ({"sku": "W1", "note": 3}, "arguments.note must be string or null"),
        ({"sku": "W1", "address": {}}, "arguments.address.city is required"),
        ({"sku": "W1", "color": "red"}, "arguments.color is not an allowed field"),
    ],
)
def test_problems_are_reported(args: dict[str, JsonValue], problem: str) -> None:
    assert check_arguments(SCHEMA, args) == problem


def test_empty_schema_accepts_anything() -> None:
    assert check_arguments({}, {"x": 1}) is None
