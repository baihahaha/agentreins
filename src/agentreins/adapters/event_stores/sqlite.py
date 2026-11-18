"""SQLite event store: the default (REQUIREMENTS D5).

Implements a port; may import only agentreins.types and agentreins.ports.
"""

import asyncio
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from agentreins.adapters.event_stores._common import EVENT_JSON, check_batch, status_after
from agentreins.types.errors import ConflictError
from agentreins.types.events import Event, RunRef, RunStarted

SCHEMA_VERSION = 1
"""Version of the table layout, stored in SQLite's ``user_version``, for future migrations."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    run_key    TEXT UNIQUE,
    session_id TEXT,
    status     TEXT NOT NULL,
    last_seq   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_status ON runs(status);
CREATE TABLE IF NOT EXISTS events (
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    seq            INTEGER NOT NULL,
    event_id       TEXT NOT NULL UNIQUE,
    type           TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    timestamp      TEXT NOT NULL,
    data           TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


class SQLiteEventStore:
    """Durable event store in one SQLite file, using only the standard library.

    - Every call runs in a worker thread (``asyncio.to_thread``) so disk I/O never
      blocks the event loop. One connection, guarded by a lock, so transactions from
      concurrent calls never interleave.
    - ``synchronous=FULL`` + WAL: when ``append`` returns, the events survive a power
      cut (ADR-0005 promise 3).
    - Several processes may share the file: ``BEGIN IMMEDIATE`` takes the write lock
      first, so the ``expected_seq`` check and the insert are one atomic step.
    """

    def __init__(self, path: str | Path = "agentreins.db", *, busy_timeout: float = 30.0) -> None:
        self._lock = threading.Lock()
        # isolation_level=None: we issue BEGIN/COMMIT ourselves.
        self._conn = sqlite3.connect(
            path, timeout=busy_timeout, isolation_level=None, check_same_thread=False
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    # --- port methods ---------------------------------------------------------------

    async def append(self, run_id: str, events: list[Event], expected_seq: int) -> None:
        check_batch(run_id, events, expected_seq)
        rows = [
            (
                e.run_id,
                e.seq,
                e.event_id,
                e.type,
                e.schema_version,
                e.timestamp.isoformat(),
                EVENT_JSON.dump_json(e).decode(),
            )
            for e in events
        ]
        await asyncio.to_thread(self._append, run_id, events, expected_seq, rows)

    async def read(self, run_id: str, after_seq: int = -1) -> list[Event]:
        rows = await asyncio.to_thread(
            self._query,
            "SELECT data FROM events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        )
        return [EVENT_JSON.validate_json(str(row[0])) for row in rows]

    async def find_run(self, key: str) -> RunRef | None:
        rows = await asyncio.to_thread(self._query, _SELECT_RUN + " WHERE run_key = ?", (key,))
        return _run_ref(rows[0]) if rows else None

    async def list_unfinished(self) -> list[RunRef]:
        rows = await asyncio.to_thread(
            self._query, _SELECT_RUN + " WHERE status = 'running' ORDER BY run_id", ()
        )
        return [_run_ref(row) for row in rows]

    async def delete_run(self, run_id: str) -> None:
        def delete() -> None:
            self._conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

        await asyncio.to_thread(self._in_transaction, delete)

    # --- extra ----------------------------------------------------------------------

    async def close(self) -> None:
        """Close the database file. The store cannot be used afterwards."""
        await asyncio.to_thread(self._conn.close)

    # --- worker-thread helpers --------------------------------------------------------

    def _append(
        self,
        run_id: str,
        events: list[Event],
        expected_seq: int,
        rows: list[tuple[str, int, str, str, int, str, str]],
    ) -> None:
        def write() -> None:
            found = self._conn.execute(
                "SELECT last_seq FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            current: int = found[0] if found else -1
            if current != expected_seq:
                raise ConflictError(f"run {run_id} is at seq {current}, expected {expected_seq}")
            if found is None:
                first = events[0]
                assert isinstance(first, RunStarted)  # guaranteed by check_batch
                try:
                    self._conn.execute(
                        "INSERT INTO runs VALUES (?, ?, ?, 'running', -1)",
                        (run_id, first.run_key, first.session_id),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ConflictError(f"run key {first.run_key!r} is already used") from exc
            self._conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            self._conn.execute(
                "UPDATE runs SET status = ?, last_seq = ? WHERE run_id = ?",
                (status_after(events[-1]), events[-1].seq, run_id),
            )

        self._in_transaction(write)

    def _in_transaction(self, work: Callable[[], None]) -> None:
        """Run ``work`` as one transaction: all of it is written, or none of it."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                work()
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _query(self, sql: str, params: tuple[object, ...]) -> list[tuple[object, ...]]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()


_SELECT_RUN = "SELECT run_id, run_key, session_id, status, last_seq FROM runs"


def _run_ref(row: tuple[object, ...]) -> RunRef:
    run_id, run_key, session_id, status, last_seq = row
    return RunRef.model_validate(
        {
            "run_id": run_id,
            "run_key": run_key,
            "session_id": session_id,
            "status": status,
            "last_seq": last_seq,
        }
    )
