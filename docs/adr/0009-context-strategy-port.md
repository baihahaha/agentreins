# ADR-0009: ContextStrategy port

- **Status:** accepted (architecture step 3). Provisional until the keep-all and truncation strategies exercise it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) C3, guarantees #1, #4, #8

## Context

Models have a context-size limit. When the conversation is too long, a strategy decides what to send to the model this turn. The event log itself is never shortened.

## Decisions

### D1. Select, don't modify

```python
class ContextStrategy(Protocol):
    async def select(self, messages: list[Message], token_budget: int) -> list[Message]: ...
```

The strategy chooses what is sent; the log stays complete. If a strategy produces new content (e.g. a model-written summary of old turns), that content is recorded as an event (`context.compacted`), so a resumed run reuses the same summary rather than generating a different one.

### D2. Rules for every strategy (documented, checked by contract tests)

1. Never separate a tool call from its result.
2. Always keep the system instructions.
3. Always keep the first user message (the original task).
4. Always keep the latest message.

These rules are enforced by the contract test suite, which every strategy (ours and third-party) should pass. The core does **not** re-check the output on every turn. That option was considered and rejected as uncommon among frameworks (LangChain's `trim_messages` and Pydantic AI history processors leave this to the strategy); providers reject broken tool pairs anyway.

### D3. When it runs

Before each model call, when the estimated size exceeds a threshold (default 80% of the model's context limit, from adapter capabilities). Also when the provider returns `ContextTooLong`, followed by one retry.

Defaults: keep everything; later, truncation (drop the oldest complete turns).

## Comparison

To be completed when built: LangChain `trim_messages`, Pydantic AI history processors, OpenAI Agents SDK sessions, Claude Agent SDK compaction.
