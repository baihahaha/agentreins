"""OutputSchema: output types -> the final_result tool, and answer validation."""

from dataclasses import dataclass

import pytest
from pydantic import BaseModel, Field

from agentreins.runtime.output import FINAL_RESULT, InvalidOutput, OutputSchema


class Line(BaseModel):
    sku: str
    quantity: int = Field(gt=0)


@dataclass
class Point:
    x: int
    y: int


def test_object_types_become_the_arguments() -> None:
    schema = OutputSchema(Line)
    assert not schema.wrapped
    assert schema.spec.name == FINAL_RESULT
    properties = schema.spec.input_schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {"sku", "quantity"}
    assert schema.validate({"sku": "W1", "quantity": "3"}) == Line(sku="W1", quantity=3)
    assert OutputSchema(Point).validate({"x": 1, "y": 2}) == Point(1, 2)


def test_other_types_are_wrapped_in_result() -> None:
    schema = OutputSchema(int)
    assert schema.wrapped
    assert schema.spec.input_schema["required"] == ["result"]
    assert schema.validate({"result": 7}) == 7
    with pytest.raises(InvalidOutput, match="result: Field required"):
        schema.validate({})


def test_wrapped_types_keep_their_definitions_reachable() -> None:
    schema = OutputSchema(list[Line])
    assert "$defs" in schema.spec.input_schema
    assert schema.validate({"result": [{"sku": "W1", "quantity": 1}]}) == [
        Line(sku="W1", quantity=1)
    ]


def test_invalid_answers_say_what_is_wrong() -> None:
    with pytest.raises(InvalidOutput, match=r"quantity: Input should be greater than 0"):
        OutputSchema(Line).validate({"sku": "W1", "quantity": -1})


def test_dump_is_json() -> None:
    assert OutputSchema(Line).dump(Line(sku="W1", quantity=2)) == {"sku": "W1", "quantity": 2}
