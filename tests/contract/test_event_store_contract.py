"""EventStore contract (ADR-0005 D5). Every store must pass every test here.

To check a new store, add it to the ``store`` fixture.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentreins.adapters.event_stores.in_memory import InMemoryEventStore
from agentreins.adapters.event_stores.sqlite import SQLiteEventStore
from agentreins.ports.event_store import EventStore
from agentreins.types.errors import ConflictError
from agentreins.types.events import Event
from builders import completed, requested, responded, simple_run, started


@pytest.fixture(params=["in_memory", "sqlite"])
async def store(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[EventStore]:
    if request.param == "in_memory":
        yield InMemoryEventStore()
    else:
        sqlite = SQLiteEventStore(tmp_path / "events.db")
        yield sqlite
        await sqlite.close()


# --- promise 1: order ----------------------------------------------------------------


async def test_read_returns_events_in_append_order(store: EventStore) -> None:
    events = simple_run("r1")
    await store.append("r1", events[:2], expected_seq=-1)
    await store.append("r1", events[2:], expected_seq=1)
    assert await store.read("r1") == events


async def test_read_after_seq(store: EventStore) -> None:
    events = simple_run("r1")
    await store.append("r1", events, expected_seq=-1)
    assert await store.read("r1", after_seq=1) == events[2:]
    assert await store.read("missing") == []


async def test_runs_are_kept_apart(store: EventStore) -> None:
    await store.append("a", simple_run("a"), expected_seq=-1)
    await store.append("b", simple_run("b"), expected_seq=-1)
    assert {e.run_id for e in await store.read("a")} == {"a"}


# --- promise 2: all-or-nothing -------------------------------------------------------


BAD_BATCHES: dict[str, tuple[list[Event], str]] = {
    "gap-in-seq": ([started("r1"), requested("r1", 2)], "should be 1"),
    "wrong-run": ([started("r1"), requested("other", 1)], "belongs to run other"),
    "no-run-started": ([requested("r1", 0)], "must start with a run.started"),
    "empty": ([], "at least one event"),
}


@pytest.mark.parametrize("case", BAD_BATCHES)
async def test_malformed_batch_writes_nothing(store: EventStore, case: str) -> None:
    batch, error = BAD_BATCHES[case]
    with pytest.raises(ValueError, match=error):
        await store.append("r1", batch, expected_seq=-1)
    assert await store.read("r1") == []
    await store.append("r1", simple_run("r1"), expected_seq=-1)  # still usable


async def test_run_started_only_first(store: EventStore) -> None:
    await store.append("r1", [started("r1")], expected_seq=-1)
    restart = started("r1").model_copy(update={"seq": 1})
    with pytest.raises(ValueError, match="only be the first event"):
        await store.append("r1", [restart], expected_seq=0)


# --- promise 4: conflicts ------------------------------------------------------------


async def test_wrong_expected_seq_is_a_conflict(store: EventStore) -> None:
    await store.append("r1", [started("r1")], expected_seq=-1)
    with pytest.raises(ConflictError):
        await store.append("r1", [started("r1")], expected_seq=-1)  # already exists
    with pytest.raises(ConflictError):
        await store.append("r1", [requested("r1", 5)], expected_seq=4)  # log is at 0
    assert len(await store.read("r1")) == 1


async def test_two_concurrent_writers_only_one_wins(store: EventStore) -> None:
    await store.append("r1", [started("r1")], expected_seq=-1)
    outcomes = await asyncio.gather(
        store.append("r1", [requested("r1", 1)], expected_seq=0),
        store.append("r1", [responded("r1", 1, text="other")], expected_seq=0),
        return_exceptions=True,
    )
    assert sum(o is None for o in outcomes) == 1
    assert sum(isinstance(o, ConflictError) for o in outcomes) == 1
    assert len(await store.read("r1")) == 2


# --- promise 5: run keys -------------------------------------------------------------


async def test_run_key_maps_to_one_run(store: EventStore) -> None:
    await store.append("r1", [started("r1", run_key="order-42")], expected_seq=-1)
    with pytest.raises(ConflictError):
        await store.append("r2", [started("r2", run_key="order-42")], expected_seq=-1)
    ref = await store.find_run("order-42")
    assert ref is not None
    assert ref.run_id == "r1"
    assert await store.read("r2") == []
    assert await store.find_run("nope") is None


async def test_runs_without_key_do_not_collide(store: EventStore) -> None:
    await store.append("r1", [started("r1")], expected_seq=-1)
    await store.append("r2", [started("r2")], expected_seq=-1)


# --- run lookup and deletion ---------------------------------------------------------


async def test_status_follows_latest_event(store: EventStore) -> None:
    events = simple_run("r1", run_key="k")
    await store.append("r1", events[:3], expected_seq=-1)
    ref = await store.find_run("k")
    assert ref is not None
    assert (ref.status, ref.last_seq) == ("running", 2)
    await store.append("r1", [completed("r1", 3)], expected_seq=2)
    ref = await store.find_run("k")
    assert ref is not None
    assert (ref.status, ref.last_seq) == ("completed", 3)


async def test_list_unfinished(store: EventStore) -> None:
    await store.append("done", simple_run("done"), expected_seq=-1)
    await store.append("busy", [started("busy")], expected_seq=-1)
    assert [r.run_id for r in await store.list_unfinished()] == ["busy"]


async def test_delete_run_removes_events_and_frees_the_key(store: EventStore) -> None:
    await store.append("r1", simple_run("r1", run_key="k"), expected_seq=-1)
    await store.append("r2", simple_run("r2"), expected_seq=-1)
    await store.delete_run("r1")
    assert await store.read("r1") == []
    assert await store.find_run("k") is None
    assert len(await store.read("r2")) == 4
    await store.append("r3", [started("r3", run_key="k")], expected_seq=-1)
    await store.delete_run("never-existed")
