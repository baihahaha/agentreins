# Architecture

**Status:** living document. Individual decisions are recorded as ADRs in [docs/adr/](docs/adr/); this file is the map.

## Component model

```text
                Application code
                       |
                       v
+------------------- Agent Runtime --------------------+
|  bounded step loop · budgets · cancellation          |
|  interrupts (approval) · hooks/middleware            |
+-------+----------------+----------------+------------+
        |                |                |
  Model Adapter    Context Manager    Tool Harness
  (Anthropic,      (what the model    registry -> validate
   OpenAI-compat,   sees this turn;   -> policy -> execute
   Fake)            budget/compact)   (timeouts, effects)
        |                                 |
   Provider HTTP                  Python tools · MCP servers
        \_____________   ________________/
                      \ /
                  Event Log  <-- single source of truth
                      |
          +-----------+------------+
          |                        |
    Event Store               Projections
    (memory, SQLite)          (message history, run state,
                               checkpoints, traces, cost)
```

## Core decisions

These are made early because they are expensive to retrofit. Each will get an ADR.

| # | Decision | ADR |
|---|---|---|
| 1 | **Event-sourced runtime.** Every model call, tool request/result, approval and error is an immutable, typed event in an append-only log. Message history, run state and checkpoints are *projections* of that log. | [0001](docs/adr/0001-content-and-event-model.md) |
| 2 | **Provider-neutral content model.** Messages are made of content blocks (`text`, `tool_use`, `tool_result`, `reasoning`, `image`) with stable call IDs, parallel tool calls, stop reasons and usage. Adapters translate; they never leak provider shapes. | 0001 |
| 3 | **Async-first, with streaming from day one.** The adapter interface streams; non-streaming is a convenience on top. | planned |
| 4 | **Tool effect classes.** `read_only`, `idempotent`, `side_effecting`. Side-effecting calls write an `intent` event with an idempotency key before execution. On resume, an intent without a result is *reconciled or escalated*, never re-run blindly. | planned |
| 5 | **Interrupts are first-class.** Approval and other waits suspend the run to the store; `resume()` continues from the log. | planned |
| 6 | **Policy lives outside the model.** A trusted hook authorizes every tool call before execution. | planned |
| 7 | **Budgets & cancellation.** Max steps, tokens, cost, wall time; per-tool timeouts. | planned |
| 8 | **One extension point: hooks.** Tracing, policy, logging and evals plug in through the same hook interface. | planned |
| 9 | **Small public API, semver.** Public = re-exported from `agentreins`. Everything else is `agentreins._internal`. | planned |

## Responsibilities and trust boundaries

- **Model Adapter.** Translates between the neutral content model and one provider's wire format. Normalizes stop reasons, usage and errors. Untrusted output: whatever the model returns is a *request*, not an action.
- **Agent Runtime.** Owns the loop: call model → record events → dispatch tool calls → decide whether to continue. Enforces budgets, handles cancellation and interrupts.
- **Tool Harness.** The trust boundary. Only registered tools run. Arguments are validated against the tool's schema (pydantic). Policy hooks authorize. Execution has a timeout. Failures become structured `tool_result` errors returned to the model, not crashes.
- **Context Manager.** Decides what the model sees each turn under a token budget. Must keep each `tool_use` paired with its `tool_result`. Pluggable strategy (truncate, summarize).
- **Event Store.** Append-only, ordered per run. In-memory and SQLite in 1.0; the interface allows others.
- **Projections.** Pure functions from events to views. Message history for the model is one projection; it is *not* the persisted state.

## Dependency policy

- **Core:** Python ≥ 3.11 standard library + `pydantic` v2. Nothing else.
- **Extras:** `agentreins[providers]` adds `httpx` for real model adapters. Future extras (`otel`, `mcp`) must stay optional.
- **No vendor SDKs.** Adapters implement provider HTTP APIs directly. This keeps the core stable when vendors change their SDKs and keeps the wire protocol visible.

## Out of scope for 1.0

Workflow/graph engine, planner, multi-agent orchestration, long-term memory, A2A, distributed execution, hosted service. Revisit after 1.0.

## Open questions

Tracked as ADRs once they are being decided:

- Exact event envelope (IDs, ordering, schema versioning) → ADR-0001
- Reconciliation contract for side-effecting tools after a crash
- Cancellation semantics while a tool is running
- Which errors trigger deterministic retry, model replan, or human escalation
- How user identity propagates to tools and policy
