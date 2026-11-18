"""Model request/response and stream events (ADR-0002 D4, D7)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from agentreins.types.budget import Usage
from agentreins.types.content import Message
from agentreins.types.model import (
    ForceTool,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ResponseComplete,
    TextDelta,
    ToolArgsDelta,
    ToolUseStart,
)
from agentreins.types.tools import Effect, ToolSpec

SPEC = ToolSpec(
    name="get_inventory",
    description="Stock on hand",
    input_schema={"type": "object"},
    effect=Effect.READ_ONLY,
)


def _response() -> ModelResponse:
    return ModelResponse(
        message=Message.assistant("40 units"),
        stop_reason="end_turn",
        usage=Usage(input_tokens=10, output_tokens=3),
        model="gpt-x",
        request_id="r1",
    )


def test_request_round_trips_with_all_fields() -> None:
    request = ModelRequest(
        model="gpt-x",
        messages=[Message.user("hi")],
        system="Be brief.",
        tools=[SPEC],
        tool_choice=ForceTool(name="get_inventory"),
        max_tokens=100,
        temperature=0.2,
        stop=["END"],
        provider_options={"seed": 7, "reasoning_effort": "low"},
    )
    assert ModelRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("choice", ["auto", "none", "required"])
def test_tool_choice_literals(choice: str) -> None:
    request = ModelRequest.model_validate({"model": "m", "messages": [], "tool_choice": choice})
    assert request.tool_choice == choice


def test_unknown_tool_choice_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelRequest.model_validate({"model": "m", "messages": [], "tool_choice": "sometimes"})


def test_response_round_trips_and_must_be_assistant() -> None:
    response = _response()
    assert ModelResponse.model_validate_json(response.model_dump_json()) == response
    with pytest.raises(ValidationError, match="assistant"):
        ModelResponse(message=Message.user("hi"), stop_reason="end_turn", usage=Usage(), model="m")


def test_unknown_stop_reason_is_rejected() -> None:
    data = _response().model_dump()
    data["stop_reason"] = "error"  # errors are exceptions, not stop reasons (ADR-0002 D5)
    with pytest.raises(ValidationError):
        ModelResponse.model_validate(data)


def test_stream_events_are_parsed_by_type() -> None:
    adapter: TypeAdapter[ModelStreamEvent] = TypeAdapter(ModelStreamEvent)
    events: list[ModelStreamEvent] = [
        TextDelta(text="4"),
        ToolUseStart(id="c1", name="t"),
        ToolArgsDelta(id="c1", delta='{"a'),
        ResponseComplete(response=_response()),
    ]
    for event in events:
        assert adapter.validate_json(adapter.dump_json(event)) == event


def test_capabilities_need_a_context_size() -> None:
    assert ModelCapabilities(max_context_tokens=128_000).parallel_tool_calls is True
    with pytest.raises(ValidationError):
        ModelCapabilities(max_context_tokens=0)
