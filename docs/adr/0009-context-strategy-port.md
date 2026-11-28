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

## Implementation notes (M5a)

The context manager estimates the request size (about 4 characters per token, counting messages, system instructions and tool specs). Above 80% of `max_context_tokens` it calls the strategy with what is left after the system instructions and tools. On `ContextTooLong` it asks the strategy for a pick at half that budget; if that drops nothing (as with keep-all), the run fails without a retry instead of sending the same request again.

## Comparison

- **LangChain `trim_messages` / Pydantic AI history processors:** functions over the message list, run before each model call, like `select`. Keeping tool calls and results together is the function's job there too.
- **OpenAI Agents SDK sessions:** store and reload history; trimming is left to the application.
- **Claude Agent SDK compaction:** summarizes old turns automatically when the window fills. A summarizing strategy would fit our port, with the summary recorded as an event (D1) so a resumed run reuses it.
