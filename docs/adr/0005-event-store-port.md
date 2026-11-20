# ADR-0005: EventStore port

- **Status:** accepted (architecture step 3). Provisional until the SQLite and in-memory stores exercise it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) C4, G4, D3 (run keys), D5 (SQLite default), guarantees #1 and #4

## Context

The event log is the single source of truth for every run. The EventStore port persists it. Guarantee #1 ("correct under failure") is only as strong as the weakest store, so the promises below are part of the contract and are checked by contract tests against every implementation.

## Decisions

### D1. One port for events and run lookup

```python
class EventStore(Protocol):
    async def append(self, run_id: str, events: list[Event], expected_seq: int) -> None: ...
    async def read(self, run_id: str, after_seq: int = -1) -> list[Event]: ...
    async def find_run(self, key: str) -> RunRef | None: ...
    async def list_unfinished(self) -> list[RunRef]: ...
    async def delete_run(self, run_id: str) -> None: ...
```

Creating a run and claiming its run key happen in one atomic operation, so two runs can never share a key. A separate lookup port was rejected: two stores could disagree after a crash.

### D2. Optimistic concurrency

Every `append` states the sequence number it expects the log to be at. If another writer got there first, the store raises `ConflictError` and nothing is written. No locks, so a crashed process never leaves a run stuck. Rejected: locks (can be left held), last-write-wins (two copies of a run could both execute side effects).

### D3. Events are immutable; whole runs can be deleted

Single events are never edited or deleted. `delete_run` removes an entire run, for retention policies and privacy law (e.g. GDPR right to be forgotten). It is an admin operation, recorded outside the deleted run.

### D4. Storage format

Events are stored as JSON with a `schema_version` per event, identical across all stores. Runs can move between stores, and old events stay readable after upgrades.

### D5. Promises (checked by contract tests)

1. `read` returns events in exactly the order they were appended.
2. One `append` is all-or-nothing, even if the process crashes mid-call.
3. When `append` returns, the events are durably saved (for SQLite: on disk).
4. Conflicting writes raise `ConflictError`; nothing is written.
5. A run key maps to at most one run.

### D6. Built-in stores (decided 2026-11-18, M2)

- **SQLite (default)** uses only the standard library `sqlite3`. Calls run in a worker thread (`asyncio.to_thread`) on one lock-guarded connection, so disk I/O never blocks the event loop. Rejected: `aiosqlite` (a dependency, so it could not be the default) and blocking calls on the event loop.
- **Durability:** WAL journal with `synchronous=FULL`, so promise 3 holds even across a power cut (about 1–5 ms per append). Rejected: `synchronous=NORMAL`, which is crash-safe but can lose the last appends on power loss.
- **Atomic append:** `BEGIN IMMEDIATE` takes the write lock before the `expected_seq` check, so several processes can share one file. The first append of a run must start with `run.started`; it creates the run and claims its run key in the same transaction.
- **Status** of a run follows its latest event (`run.completed` / `run.failed` / anything else = `running`), so a failed run that is resumed shows as running again.
- **In-memory** store for tests: same rules, not durable.
- **Contract tests** live in `tests/contract/` for now; they move into `agentreins.testing` before the v0.5 freeze so third-party stores can reuse them.

## Comparison

To be completed when built: LangGraph checkpointers (state snapshots, not an event log), Temporal event history, EventStoreDB expected-version appends.
