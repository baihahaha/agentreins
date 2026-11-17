# ADR-0002: ModelAdapter port

- **Status:** accepted (architecture step 3). Provisional until the Fake and OpenAI adapters exercise it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) C7, C8, guarantee #6; [ADR-0001](0001-content-and-event-model.md) (content model, parked)

## Context

The ModelAdapter is the port between the core and a model provider. It is the most central port: the message types it uses are shared by events, context, tools and memory, so they are the most expensive thing in the project to change later.

## Decisions

### D1. Two methods: all-at-once and streamed

```python
class ModelAdapter(Protocol):
    async def get_response(self, request: ModelRequest) -> ModelResponse: ...
    def stream_response(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...
```

Same shape as OpenAI Agents SDK and Pydantic AI. **Contract test:** for the same request, both methods must produce the same final `ModelResponse`, which catches drift between the two.

### D2. First adapters: Fake and OpenAI Chat Completions

- **Fake:** scripted and deterministic, for tests and examples.
- **OpenAI Chat Completions:** also covers Kimi, DeepSeek, Qwen, vLLM, Ollama, Azure OpenAI and most gateways (guarantee #6).
- Anthropic and OpenAI Responses come later, as separate adapters.
- Rule for any future Responses adapter: never use server-side conversation storage. The event log is the only source of truth.

### D3. Messages use content blocks

A message is `{role, content: list[Block]}` with blocks `text`, `tool_use`, `tool_result`, `reasoning`, `image`. Tool-call arguments are a parsed dict; unparseable JSON from the provider is kept and flagged, and the tool harness turns it into an error result. Tool results travel in a `user` message. The Chat Completions adapter translates to and from its flat format (`tool_calls`, `role: "tool"`).

Rationale: matches Anthropic, Gemini, OpenAI Responses, Pydantic AI and Claude Agent SDK. Adding those providers later needs no change to the core types.

### D4. Request and response

`ModelRequest`:

| Field | Meaning |
|---|---|
| `messages` | Conversation as content blocks |
| `system` | Instructions, separate from messages |
| `tools` | Tool specs: name, description, argument schema |
| `tool_choice` | `auto` / `none` / `required` / a specific tool |
| `model`, `max_tokens`, `temperature`, `stop` | Common settings |
| `provider_options: dict` | Provider-specific settings passed to the adapter untouched; recorded in the event log |

`ModelResponse`:

| Field | Meaning |
|---|---|
| `message` | The reply, as content blocks |
| `stop_reason` | Normalized: `end_turn`, `tool_use`, `max_tokens`, `stop_sequence`, `refusal` |
| `usage` | Input, output and cached tokens |
| `model`, `request_id` | Which model answered; the provider's request ID |

**Structured output** is tool-based by default: the core adds a hidden `final_result` tool whose argument schema is the requested output type and validates its arguments like any tool call. It works with every provider that supports tools. Native JSON-schema modes may be offered by an adapter later as an option.

### D5. Normalized errors; the runtime retries

Adapters translate provider errors into one list, each flagged retryable or not:

| Error | Retryable |
|---|---|
| `RateLimited` (with optional retry-after) | yes |
| `ProviderUnavailable` | yes |
| `Timeout` | yes |
| `ContextTooLong` | no (context manager must shrink) |
| `AuthFailed` | no |
| `BadRequest` | no |

**Adapters never retry.** The runtime applies one retry policy (max attempts, backoff) for all providers. Every failed attempt is recorded in the event log (guarantee #4) and counts against budgets (guarantee #3).

### D6. Async only

Adapter methods are async. The public API offers `run_sync()` for simple scripts.

### D7. Stream events

`stream_response()` yields a small set of events: `TextDelta`, `ToolUseStart` (id, name), `ToolArgsDelta`, `ReasoningDelta`, `UsageUpdate`. The **last event is always the complete `ModelResponse`**. Only the final response is recorded in the event log; deltas go to hooks and subscribers (UIs).

### D8. Capabilities

Each adapter declares `capabilities`: images, parallel tool calls, native structured output, max context tokens. The core checks them before sending a request and raises a clear agentreins error, never a confusing provider error.

### D9. Token counting is optional

`count_tokens(request) -> int` is an optional method. Without it, the context manager estimates (about 4 characters per token) and calibrates using the actual `usage` of each response. No tokenizer dependency (e.g. `tiktoken`) in the core.

## Comparison

To be completed when the adapter is built (Compare step): verify against current OpenAI Agents SDK `Model` and Pydantic AI `Model` interfaces.
