# 02 Storage: ledger, redactor, event stores, projection

## What it does

Every fact about a run is appended to an event log, in order, and never changed. The **ledger** is the only way in: it redacts each event, checks the redactor behaved, and hands the batch to an **event store** (SQLite by default) that saves it atomically and durably. The **projection** turns the log back into the conversation the model sees.

## Diagram

```text
 write path                                                     read path

 runtime                                                        runtime
   │ append(run_id, events, expected_seq)                          ▲ list[Message]
   ▼                                                               │
 Ledger ──► Redactor.redact(event)   (each event)              project_messages(events)
   │        identity unchanged? else RedactionError                ▲ list[Event]
   ▼                                                               │
 EventStore.append ── check batch ── one transaction ──► disk ──► EventStore.read
   (SQLite / in-memory)   ValueError     ConflictError
   │
   └─► returns the events *as stored*: the runtime uses these from now on
```

## Files

| File | Holds |
|---|---|
| [ledger/ledger.py](../../src/agentreins/ledger/ledger.py) | `Ledger`: redact, check, store |
| [ledger/projections.py](../../src/agentreins/ledger/projections.py) | `project_messages(events)`, a pure function |
| [adapters/event_stores/sqlite.py](../../src/agentreins/adapters/event_stores/sqlite.py) | `SQLiteEventStore`, the default (stdlib `sqlite3` only) |
| [adapters/event_stores/in_memory.py](../../src/agentreins/adapters/event_stores/in_memory.py) | `InMemoryEventStore`, for tests (not durable) |
| [adapters/event_stores/_common.py](../../src/agentreins/adapters/event_stores/_common.py) | Batch rules and run status, shared by both stores |
| [adapters/redactors/passthrough.py](../../src/agentreins/adapters/redactors/passthrough.py) | `PassThroughRedactor` (secrets redactor comes in M7) |
| [tests/contract/](../../tests/contract/) | Contract tests every store and redactor must pass |

## Walkthrough: appending a batch

The runtime has written `run.started` (seq 0) and now appends `model.requested` (seq 1) and `model.responded` (seq 2): `await ledger.append("r1", [requested, responded], expected_seq=0)`.

**1. Redact each event** ([ledger.py:37](../../src/agentreins/ledger/ledger.py#L37)). The redactor may change content (mask an email address in a tool result, say), but not identity. The ledger compares class, `event_id`, `run_id` and `seq` before and after; any difference, or any exception from the redactor, raises `RedactionError` and nothing is stored. Fail closed: a broken redactor stops the run rather than leaking data or corrupting the log.

**2. Check the batch** ([_common.py:13](../../src/agentreins/adapters/event_stores/_common.py#L13)), before touching the disk. Every event must belong to `r1`; `seq` must continue from `expected_seq` with no gaps (1, 2); a new run must start with `run.started`; no duplicate IDs. A violation is a caller bug and raises `ValueError`.

**3. One transaction** ([sqlite.py:148](../../src/agentreins/adapters/event_stores/sqlite.py#L148)). `BEGIN IMMEDIATE` takes SQLite's write lock first. Then ([sqlite.py:116](../../src/agentreins/adapters/event_stores/sqlite.py#L116)):

- read `last_seq` for `r1` from the `runs` table; if it is not 0 (`expected_seq`), someone else wrote first: `ConflictError`, nothing written;
- for a new run, insert the `runs` row and claim its `run_key` (a unique column: a second run with the same key is a `ConflictError`);
- insert the events, update `runs.last_seq` and `runs.status`;
- `COMMIT`. On any error: `ROLLBACK`, so nothing of the batch remains.

**4. Return the stored events.** The runtime must keep using *these*, not its originals, so the model sees exactly what is in the log, live and after a resume (ADR-0006 D2).

All SQLite calls run in a worker thread (`asyncio.to_thread`), so disk I/O never blocks the event loop; a lock keeps two calls from interleaving on the shared connection.

## Walkthrough: rebuilding the conversation

`project_messages` ([projections.py:25](../../src/agentreins/ledger/projections.py#L25)) walks the events once:

| Event | Becomes |
|---|---|
| `run.started` | its input messages |
| `model.responded` | the assistant message; its tool calls are now "open" |
| `message.added` | that user message (e.g. the runtime asking for a structured answer) |
| `tool.call.completed` | a `ToolResultBlock` with the tool's content |
| `tool.call.failed` | an error result: `"Tool failed: <error>"` or `"Tool timed out"` |
| `tool.call.rejected` | an error result with the rejection message |
| everything else | nothing (bookkeeping, not conversation) |

When the next `model.responded` arrives (or the events end), the open step closes: all its results go into **one** user message, **in the order of the tool calls**, not the order the tools finished. Providers reject anything else. Example: the model calls `a` and `b`, `b` finishes first; the projection still emits `[result a, result b]` ([test_parallel_tool_calls](../../tests/unit/ledger/test_projections.py#L28)).

Same events in, same messages out, every time. That determinism is what makes resume correct: the model gets exactly what it would have got without the crash.

## Guarantees

The five promises of ADR-0005 D5, checked against **both** stores by the contract tests:

| Promise | SQLite does it with | Proven by |
|---|---|---|
| 1. `read` returns events in append order | primary key `(run_id, seq)`, `ORDER BY seq` | [test_read_returns_events_in_append_order](../../tests/contract/test_event_store_contract.py#L33) |
| 2. An append is all-or-nothing | one transaction, rollback on any error | [test_malformed_batch_writes_nothing](../../tests/contract/test_event_store_contract.py#L65), [test_failure_inside_the_transaction_rolls_everything_back](../../tests/unit/adapters/test_sqlite_store.py#L28) |
| 3. Durable when `append` returns | WAL journal + `synchronous=FULL`: flushed to disk before `COMMIT` returns, survives a power cut | [test_events_survive_closing_and_reopening](../../tests/unit/adapters/test_sqlite_store.py#L13), [test_durability_settings](../../tests/unit/adapters/test_sqlite_store.py#L55) |
| 4. Conflicting writes raise `ConflictError` | `BEGIN IMMEDIATE`, then compare `last_seq` with `expected_seq` | [test_two_concurrent_writers_only_one_wins](../../tests/contract/test_event_store_contract.py#L92), [test_two_store_objects_on_one_file_detect_conflicts](../../tests/unit/adapters/test_sqlite_store.py#L43) |
| 5. A run key maps to at most one run | `run_key UNIQUE`, claimed in the same transaction as `run.started` | [test_run_key_maps_to_one_run](../../tests/contract/test_event_store_contract.py#L107) |

And for the ledger and projection:

| Promise | Proven by |
|---|---|
| A redactor that fails or changes identity stores nothing | [test_bad_redactor_fails_closed](../../tests/unit/ledger/test_ledger.py#L59) |
| The store gets the redacted events, and so does the caller | [test_store_receives_redacted_events_and_caller_gets_them_back](../../tests/unit/ledger/test_ledger.py#L49) |
| A result with no matching call, or two results for one call, is an error | [test_result_without_matching_call_is_rejected](../../tests/unit/ledger/test_projections.py#L87), [test_two_results_for_one_call_are_rejected](../../tests/unit/ledger/test_projections.py#L104) |

## Design choices

| Choice | Alternatives | Why this one | Others |
|---|---|---|---|
| **Event log** as the source of truth | State snapshots per step | Records *why* state changed (audit), and resume replays facts instead of trusting a snapshot | LangGraph checkpointers save snapshots; Temporal keeps an event history |
| **Optimistic concurrency** (`expected_seq`) | Locks; last write wins | No lock can be left held by a crashed process; two copies of a run can never both continue | EventStoreDB `expected_version` |
| **SQLite as default** | In-memory default | Guarantee #1 (correct under failure) needs durability out of the box (REQUIREMENTS D5) | |
| **Stdlib `sqlite3` in a thread** | `aiosqlite`; blocking calls | No dependency, and the event loop never blocks | |
| **`synchronous=FULL`** | `NORMAL` | `NORMAL` is crash-safe but can lose the last appends on power loss; about 1–5 ms per append is worth it | |
| **Redact on write** | Redact only when displaying | The model sees what was stored, so behaviour is identical after resume (ADR-0006 D2) | |
| **Runtime check of the redactor** | Contract tests only | One comparison per event; a buggy custom redactor cannot corrupt the log | |

## Extending it

**Your own event store** (e.g. Postgres): implement the five methods of [EventStore](../../src/agentreins/ports/event_store.py), call `check_batch` and `status_after` from [_common.py](../../src/agentreins/adapters/event_stores/_common.py) if you like, and serialize with `EVENT_JSON`. Then add your store to the `store` fixture in [test_event_store_contract.py](../../tests/contract/test_event_store_contract.py): if every contract test passes, the runtime can rely on it. (Before v0.5 the contract tests move into `agentreins.testing`, so they can be run from outside this repo.)

**Your own redactor:** one method, `async def redact(event) -> Event`. Change content with `event.model_copy(update=…)`; never change IDs, `seq` or type. A complete example that hides email addresses in tool results:

```python
import re
from agentreins.types.content import TextBlock
from agentreins.types.events import Event, ToolCallCompleted

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


class EmailRedactor:
    """Replaces email addresses in tool results before they are stored."""

    async def redact(self, event: Event) -> Event:
        if not isinstance(event, ToolCallCompleted):
            return event
        content = [
            TextBlock(text=EMAIL.sub("[email]", b.text)) if isinstance(b, TextBlock) else b
            for b in event.result.content
        ]
        result = event.result.model_copy(update={"content": content})
        return event.model_copy(update={"result": result})


ledger = Ledger(SQLiteEventStore("agentreins.db"), EmailRedactor())
# a tool returning "Contact: ana@acme.com" is stored, and later shown to the model, as "Contact: [email]"
```

No base class is needed: any class with a matching `redact` method fits the port, and pyright checks the signature. To prove it is a *correct* redactor, add it to the `redactor` fixture in [test_redactor_contract.py](../../tests/contract/test_redactor_contract.py): the contract tests check it never changes an event's ID, `seq` or type.

## Known limits

- **One SQLite file, one writer at a time.** Fine for one machine and many runs; not a shared multi-server store. That is what a Postgres store is for.
- **The in-memory store is not durable** and is for tests only.
- **Calls without an outcome are left out of the projection.** A crash between `tool.call.started` and its outcome leaves an open call; recovery (M6) decides whether to re-run it, reconcile it, or ask a human.
- **`delete_run` is not yet recorded anywhere.** ADR-0005 D3 says deletions are recorded outside the deleted run; that admin log does not exist yet.
- **No schema migrations yet.** The table layout version is stored (`PRAGMA user_version = 1`) for when one is needed.
