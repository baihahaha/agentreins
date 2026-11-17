# ADR-0007: Hooks port

- **Status:** accepted (architecture step 3). Provisional until the OpenTelemetry exporter exercises it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) G7, C6 (event stream for UIs)

## Context

Hooks let outside code watch each step of a run: tracing, logging, metrics, live UIs. Hooks are **optional**: none are registered by default and the runtime works fully without them. The dispatch mechanism is part of the core (`runtime/hooks.py`).

## Decisions

### D1. One method

```python
class Hooks(Protocol):
    async def on_event(self, event: Event | ModelStreamEvent) -> None: ...
```

Receives every stored event and every stream delta. New event types reach hooks with no interface change. A helper base class offers specific methods (`on_tool_start`, `on_model_end`…) for convenience. Rejected as the port itself: many specific methods (OpenAI Agents SDK style), which grow with every new event type.

### D2. Observe only

Hooks cannot change or stop a run. Blocking is Policy's job (ADR-0004); changing data is the Redactor's (ADR-0006). Rejected: blocking hooks (Claude Agent SDK style), which would create a second, unaudited decision point.

### D3. Failures are logged; the run continues

A hook that raises is logged and skipped; each hook call has a time limit. Hooks are best effort: anything needing every event guaranteed (e.g. audit export) reads the event store.

## Comparison

To be completed when built: OpenAI Agents SDK `RunHooks`, Claude Agent SDK hooks, OpenTelemetry span processors.
