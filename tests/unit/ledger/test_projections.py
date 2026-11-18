"""Projection: events -> messages (ADR-0001 rules). Pure and deterministic."""

import pytest

from agentreins.ledger.projections import ProjectionError, project_messages
from agentreins.types.content import TextBlock, ToolResultBlock, ToolUseBlock
from agentreins.types.events import Event, ToolCallFailed, ToolCallRejected
from builders import requested, responded, started, tool_completed, tool_started

R = "r1"


def parallel_calls_run() -> list[Event]:
    """Model asks for two tools; b finishes before a; then the model answers."""
    return [
        started(R, text="compare a and b"),
        requested(R, 1),
        responded(R, 2, text="checking", calls=("a", "b")),
        tool_started(R, 3, "a"),
        tool_started(R, 4, "b"),
        tool_completed(R, 5, "b", "B=2"),
        tool_completed(R, 6, "a", "A=1"),
        requested(R, 7, step=2),
        responded(R, 8, text="a < b", step=2),
    ]


def test_parallel_tool_calls() -> None:
    messages = project_messages(parallel_calls_run())
    assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0].text == "compare a and b"
    assert [b.id for b in messages[1].content if isinstance(b, ToolUseBlock)] == ["a", "b"]
    results = messages[2].content
    # Ordered like the calls (a, b), not like completion (b, a).
    assert [r.tool_use_id for r in results if isinstance(r, ToolResultBlock)] == ["a", "b"]
    assert messages[3].text == "a < b"


def test_projection_is_deterministic() -> None:
    events = parallel_calls_run()
    assert project_messages(events) == project_messages(events)


def test_failed_and_rejected_calls_become_error_results() -> None:
    messages = project_messages(
        [
            started(R),
            responded(R, 1, calls=("x", "y", "z")),
            ToolCallFailed(run_id=R, seq=2, call_id="x", error="boom", duration_ms=1),
            ToolCallFailed(run_id=R, seq=3, call_id="y", error="", timed_out=True, duration_ms=1),
            ToolCallRejected(
                run_id=R, seq=4, call_id="z", reason="policy_denied", message="not allowed"
            ),
        ]
    )
    results = [b for b in messages[-1].content if isinstance(b, ToolResultBlock)]
    assert all(r.is_error for r in results)
    texts = [r.content[0] for r in results]
    assert texts == [
        TextBlock(text="Tool failed: boom"),
        TextBlock(text="Tool timed out"),
        TextBlock(text="not allowed"),
    ]


def test_call_without_outcome_is_left_out() -> None:
    messages = project_messages(
        [started(R), responded(R, 1, calls=("a", "b")), tool_completed(R, 2, "a", "ok")]
    )
    results = [b for b in messages[-1].content if isinstance(b, ToolResultBlock)]
    assert [r.tool_use_id for r in results] == ["a"]


def test_result_without_matching_call_is_rejected() -> None:
    with pytest.raises(ProjectionError, match="no matching tool call"):
        project_messages([started(R), responded(R, 1, text="hi"), tool_completed(R, 2, "x", "?")])


def test_result_for_an_earlier_step_is_rejected() -> None:
    with pytest.raises(ProjectionError):
        project_messages(
            [
                started(R),
                responded(R, 1, calls=("a",)),
                responded(R, 2, text="moved on", step=2),
                tool_completed(R, 3, "a", "late"),
            ]
        )


def test_two_results_for_one_call_are_rejected() -> None:
    with pytest.raises(ProjectionError, match="more than one result"):
        project_messages(
            [
                started(R),
                responded(R, 1, calls=("a",)),
                tool_completed(R, 2, "a", "1"),
                tool_completed(R, 3, "a", "2"),
            ]
        )
