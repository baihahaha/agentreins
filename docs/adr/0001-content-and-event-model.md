# ADR-0001: Content and event model

- **Status:** accepted 2026-11-18. Provisional until M1/M2 exercise it; frozen at v0.5.
- **Date:** 2026-11-16 (drafted), 2026-11-18 (accepted)

## Context

Every other component depends on two data shapes:

1. **Content model:** how a conversation turn is represented independent of any provider (Anthropic content blocks vs OpenAI `tool_calls` vs others).
2. **Event model:** what gets durably recorded so a run can be audited, resumed after a crash, and replayed in tests.

The prior draft asked "should the internal event log and provider message history use the same schema?" This ADR answers: **no.** Events are the source of truth; messages are a projection.

## Part 1: Content model

### Options

1. **Flat messages** (`role`, `content: str`, optional `tool_calls`), as in OpenAI Chat Completions. Simple, but it can't represent interleaved text + tool calls, reasoning blocks or images cleanly.
2. **Content blocks** (`role`, `content: list[Block]`), as in Anthropic Messages. Strictly more expressive; OpenAI shapes map into it losslessly.

### Decision: content blocks (confirmed in ADR-0002 D3)

```text
Message   = { role: "user" | "assistant", content: list[Block] }
Block     = TextBlock      { text }
          | ToolUseBlock   { id, name, arguments: dict }
          | ToolResultBlock{ tool_use_id, content: list[TextBlock|ImageBlock], is_error }
          | ReasoningBlock { text, provider_signature? }   # opaque, round-tripped as-is
          | ImageBlock     { media_type, data | url }
```

- **System prompt** is a run-level field, not a message (providers disagree on where it goes).
- **Tool result messages** use role `user` (Anthropic convention). The OpenAI adapter maps each `ToolResultBlock` to a `role: "tool"` message.
- **`ToolUseBlock.id`** comes from the provider when it has one. **Decided:** agentreins also mints its own `call_id` and keeps the provider ID as metadata. Our ID is stable across providers and resumes, and it becomes the idempotency-key basis in a later ADR.
- **`arguments`** are kept as the raw parsed dict. Validation happens in the tool harness, *not* here. If the provider returns unparseable JSON, the block holds the raw string and a parse-error flag so the harness can reply with a structured error.
- **Stop reason** is normalized: `end_turn | tool_use | max_tokens | stop_sequence | refusal` (as in ADR-0002 D4; provider failures are raised as errors, not stop reasons).
- **Usage** is normalized: `input_tokens, output_tokens, cache_read_tokens, cache_write_tokens`.

## Part 2: Event model

### Envelope (every event)

```text
Event = {
  event_id:   ULID           # globally unique, time-sortable
  run_id:     ULID
  seq:        int            # 0,1,2… per run, strictly increasing, no gaps
  type:       str            # discriminator, e.g. "tool.call.requested"
  schema_version: int        # per event type, for future migrations
  timestamp:  datetime (UTC)
  payload:    type-specific
}
```

`seq` (not timestamp) defines order. The store rejects an append whose `seq` ≠ last + 1. That gives optimistic concurrency for free: two processes resuming the same run cannot both win.

### Event types for v0.1–v0.3

| Type | Payload | Notes |
|---|---|---|
| `run.started` | task input, system prompt, tool specs, budgets, model id | Enough to rebuild the run config on resume |
| `model.requested` | step number, projected message count / hash | Records *that* we asked; the full prompt is reproducible from prior events |
| `model.responded` | assistant `Message`, stop reason, usage, latency | |
| `model.failed` | error class, retryable flag | |
| `tool.call.requested` | call_id, name, arguments | One per `ToolUseBlock`; emitted from the model response |
| `tool.call.rejected` | call_id, reason (`unknown_tool`, `invalid_arguments`, `policy_denied`) | Harness decision, never executed |
| `tool.call.started` | call_id, effect class, idempotency key | **The intent record.** For side-effecting tools this is written *before* execution |
| `tool.call.completed` | call_id, result content, duration | |
| `tool.call.failed` | call_id, error, timeout flag | |
| `run.completed` | final message, total usage/cost | |
| `run.failed` | reason (`max_steps`, `budget_exceeded`, `error`, `cancelled`) | |

Later ADRs add `run.interrupted` / `run.resumed` (approvals) and `context.compacted`.

### Rules

- **Events are immutable facts about the past.** Name them in past tense; never update or delete.
- **Message history is a projection:** `project_messages(events) -> list[Message]`, a pure function. The context manager later chooses which part of that projection the model sees.
- **Crash semantics fall out of the log:** `tool.call.started` without `completed`/`failed` = "unknown outcome". What to do then (re-run if idempotent, reconcile or escalate if side-effecting) is the subject of the durability ADR.
- **Full model inputs are not persisted (decided).** They are reproducible from prior events plus the run config, as long as projection is deterministic. Store a hash in `model.requested` so non-determinism is detectable.
- **Streaming deltas are not recorded as events (decided; see ADR-0002 D7).** Deltas go to hooks/subscribers only. Only the completed `model.responded` is durable.

## Consequences

- Resume, audit, replay tests and cost accounting all read one log. There is no second source of truth to drift.
- Every adapter has to map into content blocks. That's more work for OpenAI-style APIs, but the work is contained.
- Projection must be deterministic. That needs tests from day one.
- The event schema becomes a public, versioned contract (stored data outlives code), hence `schema_version`.

## Comparison (to fill in after implementation)

- **LangGraph:** checkpoints full channel state snapshots per super-step instead of an event log. Simpler resume; weaker audit trail of *why* the state changed.
- **OpenAI Agents SDK:** the run's item list (`RunItem`s) is close to our event list but kept in memory; durability is delegated to sessions/external stores.
- **Temporal-style durable execution:** our model is a lightweight cousin, with an event history plus deterministic replay, minus the workflow engine.

Maintainer: verify these against current source/docs when you do the Compare step.

## Implementation (after accepting this ADR)

Built in milestone M1 (types) and M2 (projection), written by the coding agent and reviewed by the maintainer (see [LEARNING_PROTOCOL.md](../dev/LEARNING_PROTOCOL.md)):
1. The content blocks and `Message` as pydantic models (discriminated union on `type`), in `src/agentreins/types/content.py`.
2. The event envelope and the event types above, in `src/agentreins/types/events.py`.
3. `project_messages(events)`, in `src/agentreins/ledger/projections.py`.
4. Tests: round-trip JSON serialization of every event; projection of a run with two parallel tool calls; projection rejects a `tool_result` whose `tool_use_id` has no matching request.
