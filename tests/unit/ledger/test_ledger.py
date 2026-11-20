"""Ledger: redaction happens before storage, and fails closed (ADR-0006)."""

import pytest

from agentreins.adapters.event_stores.in_memory import InMemoryEventStore
from agentreins.adapters.redactors.passthrough import PassThroughRedactor
from agentreins.ledger.ledger import Ledger
from agentreins.ports.redactor import Redactor
from agentreins.types.errors import RedactionError
from agentreins.types.events import Event, RunStarted
from builders import responded, simple_run, started


class MaskWords:
    """Removes the user's input: a content-only change, which is allowed."""

    async def redact(self, event: Event) -> Event:
        if isinstance(event, RunStarted):
            return event.model_copy(update={"input": []})
        return event


class ChangesSeq:
    async def redact(self, event: Event) -> Event:
        return event.model_copy(update={"seq": event.seq + 100})


class ChangesType:
    async def redact(self, event: Event) -> Event:
        if isinstance(event, RunStarted):
            return responded(event.run_id, event.seq).model_copy(
                update={"event_id": event.event_id}
            )
        return event


class Crashes:
    async def redact(self, event: Event) -> Event:
        raise RuntimeError("pattern file missing")


async def test_append_and_read_round_trip() -> None:
    ledger = Ledger(InMemoryEventStore(), PassThroughRedactor())
    events = simple_run("r1")
    assert await ledger.append("r1", events, expected_seq=-1) == events
    assert await ledger.read("r1") == events


async def test_store_receives_redacted_events_and_caller_gets_them_back() -> None:
    store = InMemoryEventStore()
    stored = await Ledger(store, MaskWords()).append("r1", [started("r1")], expected_seq=-1)
    first = stored[0]
    assert isinstance(first, RunStarted)
    assert first.input == []
    assert await store.read("r1") == stored


@pytest.mark.parametrize("redactor", [ChangesSeq(), ChangesType(), Crashes()])
async def test_bad_redactor_fails_closed(redactor: Redactor) -> None:
    store = InMemoryEventStore()
    with pytest.raises(RedactionError):
        await Ledger(store, redactor).append("r1", simple_run("r1"), expected_seq=-1)
    assert await store.read("r1") == []
