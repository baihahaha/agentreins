"""Projections: events -> message history. Pure functions (ADR-0001 rules).

The same events always give the same messages. That is what lets a resumed run send
the model exactly what it would have sent before the crash.
"""

from collections.abc import Sequence

from agentreins.types.content import Message, TextBlock, ToolResultBlock, ToolUseBlock
from agentreins.types.events import (
    Event,
    ModelResponded,
    RunStarted,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRejected,
)


class ProjectionError(ValueError):
    """The events do not form a valid conversation (a bug, never expected in practice)."""


def project_messages(events: Sequence[Event]) -> list[Message]:
    """Rebuild the conversation from a run's events.

    - ``run.started`` -> its input messages; ``model.responded`` -> the assistant message.
    - Tool outcomes (completed / failed / rejected) -> one ``user`` message per model
      step, results in the same order as the tool calls (providers require this), not
      in the order the tools finished.
    - A call with no outcome yet is left out; recovery (M6) decides what to do with it.
    - Other events (model.requested, model.failed, tool.call.requested/started,
      run.completed/failed) are bookkeeping and not part of the conversation.
    """
    messages: list[Message] = []
    open_calls: list[str] = []
    results: dict[str, ToolResultBlock] = {}

    def close_step() -> None:
        blocks = [results.pop(call_id) for call_id in open_calls if call_id in results]
        if blocks:
            messages.append(Message(role="user", content=list(blocks)))
        open_calls.clear()

    def add_result(call_id: str, block: ToolResultBlock) -> None:
        if call_id not in open_calls:
            raise ProjectionError(f"tool result for {call_id!r} has no matching tool call")
        if call_id in results:
            raise ProjectionError(f"tool call {call_id!r} has more than one result")
        results[call_id] = block

    for event in events:
        match event:
            case RunStarted():
                messages.extend(event.input)
            case ModelResponded():
                close_step()
                message = event.response.message
                messages.append(message)
                open_calls.extend(b.id for b in message.content if isinstance(b, ToolUseBlock))
            case ToolCallCompleted():
                add_result(
                    event.call_id,
                    ToolResultBlock(
                        tool_use_id=event.call_id,
                        content=event.result.content,
                        is_error=event.result.is_error,
                    ),
                )
            case ToolCallFailed():
                reason = "timed out" if event.timed_out else f"failed: {event.error}"
                add_result(event.call_id, _error(event.call_id, f"Tool {reason}"))
            case ToolCallRejected():
                add_result(event.call_id, _error(event.call_id, event.message))
            case _:
                pass
    close_step()
    return messages


def _error(call_id: str, text: str) -> ToolResultBlock:
    return ToolResultBlock(tool_use_id=call_id, content=[TextBlock(text=text)], is_error=True)
