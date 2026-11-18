"""In-memory event store: opt-in, for tests and experiments. Not durable.

Implements a port; may import only agentreins.types and agentreins.ports.
"""

from agentreins.adapters.event_stores._common import check_batch, status_after
from agentreins.types.errors import ConflictError
from agentreins.types.events import Event, RunRef, RunStarted


class InMemoryEventStore:
    """Keeps every run in a dict. Lost when the process exits.

    No lock is needed: ``append`` never awaits, so on one event loop it runs from start
    to finish without interruption, which makes it all-or-nothing.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = {}
        self._runs: dict[str, RunRef] = {}
        self._keys: dict[str, str] = {}

    async def append(self, run_id: str, events: list[Event], expected_seq: int) -> None:
        check_batch(run_id, events, expected_seq)
        run = self._runs.get(run_id)
        current = run.last_seq if run else -1
        if current != expected_seq:
            raise ConflictError(f"run {run_id} is at seq {current}, expected {expected_seq}")
        if run is None:
            first = events[0]
            assert isinstance(first, RunStarted)  # guaranteed by check_batch
            if first.run_key is not None and first.run_key in self._keys:
                raise ConflictError(f"run key {first.run_key!r} is already used")
            run = RunRef(
                run_id=run_id,
                run_key=first.run_key,
                session_id=first.session_id,
                status="running",
                last_seq=events[-1].seq,
            )
            if first.run_key is not None:
                self._keys[first.run_key] = run_id
            self._events[run_id] = []
        self._events[run_id].extend(events)
        self._runs[run_id] = run.model_copy(
            update={"status": status_after(events[-1]), "last_seq": events[-1].seq}
        )

    async def read(self, run_id: str, after_seq: int = -1) -> list[Event]:
        return [e for e in self._events.get(run_id, []) if e.seq > after_seq]

    async def find_run(self, key: str) -> RunRef | None:
        run_id = self._keys.get(key)
        return self._runs[run_id] if run_id else None

    async def list_unfinished(self) -> list[RunRef]:
        return sorted(
            (r for r in self._runs.values() if r.status == "running"), key=lambda r: r.run_id
        )

    async def delete_run(self, run_id: str) -> None:
        run = self._runs.pop(run_id, None)
        self._events.pop(run_id, None)
        if run and run.run_key is not None:
            self._keys.pop(run.run_key, None)
