"""Event envelope and event types (ADR-0001 Part 2)."""

from datetime import datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from agentreins.types.budget import Budget, Usage
from agentreins.types.content import Message, ToolUseBlock
from agentreins.types.events import (
    Event,
    MessageAdded,
    ModelFailed,
    ModelRequested,
    ModelResponded,
    RunCompleted,
    RunFailed,
    RunRef,
    RunStarted,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRejected,
    ToolCallRequested,
    ToolCallStarted,
)
from agentreins.types.identity import Credentials, Principal
from agentreins.types.model import ModelResponse
from agentreins.types.tools import Effect, ToolResult, ToolSpec

EVENTS = TypeAdapter[Event](Event)
RUN = "run-1"
PRINCIPAL = Principal(id="u1", tenant="acme", roles=["buyer"], attributes={"region": "eu"})
SPEC = ToolSpec(
    name="create_po",
    description="Create a purchase order",
    input_schema={"type": "object"},
    effect=Effect.SIDE_EFFECTING,
    requires=["erp"],
)
REPLY = Message(
    role="assistant",
    content=[ToolUseBlock(id="c1", provider_id="call_abc", name="create_po", arguments={"n": 2})],
)


def one_of_each() -> list[Event]:
    """A plausible run that uses every event type once."""
    return [
        RunStarted(
            run_id=RUN,
            seq=0,
            input=[Message.user("Order 2 widgets")],
            system="You are a buyer.",
            model="gpt-test",
            tools=[SPEC],
            budget=Budget(max_steps=5),
            principal=PRINCIPAL,
            session_id="s1",
            run_key="order-42",
        ),
        ModelRequested(run_id=RUN, seq=1, step=1, message_count=1, input_fingerprint="ab12"),
        ModelFailed(run_id=RUN, seq=2, step=1, attempt=1, error="RateLimited", retryable=True),
        ModelResponded(
            run_id=RUN,
            seq=3,
            step=1,
            response=ModelResponse(
                message=REPLY, stop_reason="tool_use", usage=Usage(input_tokens=9), model="m"
            ),
            latency_ms=120.5,
        ),
        ToolCallRequested(run_id=RUN, seq=4, call_id="c1", name="create_po", arguments={"n": 2}),
        ToolCallRejected(
            run_id=RUN, seq=5, call_id="c0", reason="unknown_tool", message="no such tool"
        ),
        ToolCallStarted(
            run_id=RUN, seq=6, call_id="c1", effect=Effect.SIDE_EFFECTING, idempotency_key="k1"
        ),
        ToolCallFailed(run_id=RUN, seq=7, call_id="c1", error="boom", duration_ms=3.0),
        ToolCallCompleted(
            run_id=RUN, seq=8, call_id="c1", result=ToolResult.text("PO-7"), duration_ms=40.0
        ),
        RunCompleted(
            run_id=RUN, seq=9, output=Message.assistant("Done: PO-7"), usage=Usage(input_tokens=9)
        ),
        RunFailed(run_id=RUN, seq=10, reason="cancelled"),
        MessageAdded(run_id=RUN, seq=11, message=Message.user("Please answer."), origin="runtime"),
    ]


def test_every_event_type_is_covered() -> None:
    types = {type(e) for e in one_of_each()}
    assert len(types) == 12


@pytest.mark.parametrize("event", one_of_each(), ids=lambda e: e.type)
def test_event_round_trips_through_the_union(event: Event) -> None:
    restored = EVENTS.validate_json(EVENTS.dump_json(event))
    assert type(restored) is type(event)
    assert restored == event


def test_events_are_flat_json() -> None:
    data = EVENTS.dump_python(one_of_each()[6], mode="json")
    assert data["type"] == "tool.call.started"
    assert data["call_id"] == "c1"
    assert data["effect"] == "side_effecting"
    assert "payload" not in data


def test_envelope_defaults() -> None:
    a = RunFailed(run_id=RUN, seq=0, reason="error")
    b = RunFailed(run_id=RUN, seq=1, reason="error")
    assert a.event_id != b.event_id
    assert a.schema_version == 1
    assert isinstance(a.timestamp, datetime)
    assert a.timestamp.tzinfo is not None


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENTS.validate_python({"type": "run.exploded", "run_id": RUN, "seq": 0})


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RunFailed(run_id=RUN, seq=0, reason="error", timestamp=datetime(2026, 1, 1))


@pytest.mark.parametrize("bad", [{"seq": -1}, {"schema_version": 0}, {"extra": 1}])
def test_envelope_validation(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RunFailed.model_validate({"run_id": RUN, "seq": 0, "reason": "error"} | bad)


def test_events_are_immutable() -> None:
    event = RunFailed(run_id=RUN, seq=0, reason="error")
    with pytest.raises(ValidationError):
        event.seq = 5  # pyright: ignore[reportAttributeAccessIssue]


def test_run_started_records_governance_and_principal() -> None:
    started = one_of_each()[0]
    assert isinstance(started, RunStarted)
    assert started.governance_lifted is False
    assert started.principal.roles == ["buyer"]


def test_credentials_cannot_enter_an_event() -> None:
    secret = Credentials("erp", "s3cret")
    with pytest.raises(ValidationError):
        Principal.model_validate({"id": "u1", "attributes": {"token": secret}})
    with pytest.raises(ValidationError):
        ToolCallRequested.model_validate(
            {"run_id": RUN, "seq": 0, "call_id": "c", "name": "t", "arguments": {"k": secret}}
        )


def test_run_ref() -> None:
    ref = RunRef(run_id=RUN, run_key="order-42", status="running", last_seq=3)
    assert ref.session_id is None
    with pytest.raises(ValidationError):
        RunRef(run_id=RUN, status="paused", last_seq=0)  # pyright: ignore[reportArgumentType]


def test_added_messages_are_user_messages() -> None:
    with pytest.raises(ValidationError, match="role 'user'"):
        MessageAdded(run_id=RUN, seq=0, message=Message.assistant("hi"), origin="runtime")
