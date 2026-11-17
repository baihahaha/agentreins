"""EventStore port (ADR-0005)."""

from typing import Protocol

from agentreins.types.events import Event, RunRef


class EventStore(Protocol):
    """Persists the event log. Must keep the five promises of ADR-0005 D5
    (order, all-or-nothing, durable on return, conflict detection, unique run keys)."""

    async def append(self, run_id: str, events: list[Event], expected_seq: int) -> None:
        """Append atomically; raise ConflictError if the log is not at expected_seq."""
        ...

    async def read(self, run_id: str, after_seq: int = -1) -> list[Event]: ...

    async def find_run(self, key: str) -> RunRef | None: ...

    async def list_unfinished(self) -> list[RunRef]: ...

    async def delete_run(self, run_id: str) -> None:
        """Delete a whole run (retention / privacy). Single events are never edited."""
        ...
