"""Builders for realistic event sequences, shared by contract and unit tests."""

from agentreins.types.budget import Usage
from agentreins.types.content import Message, TextBlock, ToolUseBlock
from agentreins.types.events import (
    Event,
    ModelRequested,
    ModelResponded,
    RunCompleted,
    RunStarted,
    ToolCallCompleted,
    ToolCallStarted,
)
from agentreins.types.identity import Principal
from agentreins.types.model import ModelResponse
from agentreins.types.tools import Effect, ToolResult

PRINCIPAL = Principal(id="u1", tenant="acme")


def started(run_id: str, *, run_key: str | None = None, text: str = "hi") -> RunStarted:
    return RunStarted(
        run_id=run_id,
        seq=0,
        input=[Message.user(text)],
        model="fake",
        principal=PRINCIPAL,
        run_key=run_key,
    )


def requested(run_id: str, seq: int, step: int = 1) -> ModelRequested:
    return ModelRequested(run_id=run_id, seq=seq, step=step, message_count=1, input_fingerprint="f")


def responded(
    run_id: str, seq: int, *, text: str = "", calls: tuple[str, ...] = (), step: int = 1
) -> ModelResponded:
    blocks: list[TextBlock | ToolUseBlock] = [TextBlock(text=text)] if text else []
    blocks += [ToolUseBlock(id=c, name="lookup", arguments={"q": c}) for c in calls]
    return ModelResponded(
        run_id=run_id,
        seq=seq,
        step=step,
        response=ModelResponse(
            message=Message(role="assistant", content=list(blocks)),
            stop_reason="tool_use" if calls else "end_turn",
            usage=Usage(input_tokens=1),
            model="fake",
        ),
        latency_ms=1.0,
    )


def tool_started(run_id: str, seq: int, call_id: str) -> ToolCallStarted:
    return ToolCallStarted(
        run_id=run_id, seq=seq, call_id=call_id, effect=Effect.READ_ONLY, idempotency_key=call_id
    )


def tool_completed(run_id: str, seq: int, call_id: str, text: str) -> ToolCallCompleted:
    return ToolCallCompleted(
        run_id=run_id, seq=seq, call_id=call_id, result=ToolResult.text(text), duration_ms=1.0
    )


def completed(run_id: str, seq: int) -> RunCompleted:
    return RunCompleted(run_id=run_id, seq=seq, output=Message.assistant("done"), usage=Usage())


def simple_run(run_id: str, *, run_key: str | None = None) -> list[Event]:
    """started -> model asked -> answered -> completed: seq 0..3."""
    return [
        started(run_id, run_key=run_key),
        requested(run_id, 1),
        responded(run_id, 2, text="hello"),
        completed(run_id, 3),
    ]
