"""Ledger: append events (redacted first) and read them.

See ADR-0005, ADR-0006. The runtime never talks to the EventStore directly, so
redaction cannot be skipped.
"""

from agentreins.ports.event_store import EventStore
from agentreins.ports.redactor import Redactor
from agentreins.types.errors import RedactionError
from agentreins.types.events import Event


class Ledger:
    """The only way events enter the log: redact, check, then store."""

    def __init__(self, store: EventStore, redactor: Redactor) -> None:
        self._store = store
        self._redactor = redactor

    async def append(self, run_id: str, events: list[Event], expected_seq: int) -> list[Event]:
        """Redact and store ``events`` atomically; return them *as stored*.

        The caller must use the returned events from here on (e.g. to build the model's
        context), so the model sees exactly what is in the log (ADR-0006 D2).

        Raises ``RedactionError`` if the redactor fails or breaks its contract (nothing
        is stored), and ``ConflictError`` if another writer got there first.
        """
        redacted = [await self._redact(event) for event in events]
        await self._store.append(run_id, redacted, expected_seq)
        return redacted

    async def read(self, run_id: str, after_seq: int = -1) -> list[Event]:
        """Return the run's events with ``seq > after_seq``, as stored (redacted)."""
        return await self._store.read(run_id, after_seq)

    async def _redact(self, event: Event) -> Event:
        try:
            out = await self._redactor.redact(event)
        except Exception as exc:
            raise RedactionError(f"redactor failed on {event.type} seq {event.seq}") from exc
        # Fail closed: content may change, identity may not (ADR-0006 D1).
        if (type(out), out.event_id, out.run_id, out.seq) != (
            type(event),
            event.event_id,
            event.run_id,
            event.seq,
        ):
            raise RedactionError(
                f"redactor changed the identity of {event.type} seq {event.seq}; "
                "it may change content only"
            )
        return out
