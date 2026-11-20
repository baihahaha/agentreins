"""Rules shared by every built-in event store (ADR-0005)."""

from collections.abc import Sequence

from pydantic import TypeAdapter

from agentreins.types.events import Event, RunCompleted, RunFailed, RunStarted, RunStatus

EVENT_JSON: TypeAdapter[Event] = TypeAdapter(Event)
"""Serializes any event to JSON and back to its exact class (ADR-0005 D4)."""


def check_batch(run_id: str, events: Sequence[Event], expected_seq: int) -> None:
    """Reject a malformed batch before anything is written.

    These are caller bugs (``ValueError``), not concurrency conflicts (``ConflictError``).
    """
    if not events:
        raise ValueError("append needs at least one event")
    if expected_seq < -1:
        raise ValueError(f"expected_seq must be >= -1, got {expected_seq}")
    if expected_seq == -1 and not isinstance(events[0], RunStarted):
        raise ValueError("a new run must start with a run.started event")
    seen: set[str] = set()
    for offset, event in enumerate(events, start=1):
        if event.run_id != run_id:
            raise ValueError(f"event {event.event_id} belongs to run {event.run_id}, not {run_id}")
        if event.seq != expected_seq + offset:
            raise ValueError(f"event seq {event.seq} should be {expected_seq + offset}")
        if isinstance(event, RunStarted) and event.seq != 0:
            raise ValueError("run.started can only be the first event of a run")
        if event.event_id in seen:
            raise ValueError(f"duplicate event_id {event.event_id} in batch")
        seen.add(event.event_id)


def status_after(event: Event) -> RunStatus:
    """A run's status is decided by its latest event.

    ``running`` again after ``run.failed`` is allowed: a failed run can be resumed
    (ADR-0006 D3).
    """
    if isinstance(event, RunCompleted):
        return "completed"
    if isinstance(event, RunFailed):
        return "failed"
    return "running"
