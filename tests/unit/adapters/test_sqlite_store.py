"""SQLite-only behaviour, beyond the shared contract."""

import sqlite3
from pathlib import Path

import pytest

from agentreins.adapters.event_stores.sqlite import SCHEMA_VERSION, SQLiteEventStore
from agentreins.types.errors import ConflictError
from builders import requested, simple_run, started


async def test_events_survive_closing_and_reopening(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    first = SQLiteEventStore(path)
    events = simple_run("r1", run_key="k")
    await first.append("r1", events, expected_seq=-1)
    await first.close()

    second = SQLiteEventStore(path)
    assert await second.read("r1") == events
    ref = await second.find_run("k")
    assert ref is not None
    assert ref.status == "completed"
    await second.close()


async def test_failure_inside_the_transaction_rolls_everything_back(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    a = simple_run("a")
    await store.append("a", a, expected_seq=-1)
    # Passes the batch checks but collides with an event_id already on disk, so the
    # database rejects it half-way: after the runs row was inserted.
    clash = requested("b", 1).model_copy(update={"event_id": a[0].event_id})
    with pytest.raises(sqlite3.IntegrityError):
        await store.append("b", [started("b", run_key="kb"), clash], expected_seq=-1)
    assert await store.read("b") == []
    assert await store.find_run("kb") is None
    await store.append("b", [started("b", run_key="kb")], expected_seq=-1)  # clean retry
    await store.close()


async def test_two_store_objects_on_one_file_detect_conflicts(tmp_path: Path) -> None:
    """Like two processes sharing the database."""
    path = tmp_path / "events.db"
    one, two = SQLiteEventStore(path), SQLiteEventStore(path)
    await one.append("r1", [started("r1")], expected_seq=-1)
    await one.append("r1", [requested("r1", 1)], expected_seq=0)
    with pytest.raises(ConflictError):
        await two.append("r1", [requested("r1", 1)], expected_seq=0)
    await one.close()
    await two.close()


async def test_durability_settings(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    await store.close()
    conn = sqlite3.connect(tmp_path / "events.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
