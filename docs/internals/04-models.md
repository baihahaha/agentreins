# 04 Models: the fake model and the OpenAI-compatible adapter

## What it does

A **model adapter** sends a `ModelRequest` to a model provider and returns a `ModelResponse`, either all at once (`get_response`) or piece by piece (`stream_response`). It translates between our content blocks and the provider's format, and turns every provider failure into one of our normalized errors. It never retries: that is the runtime's job. Two adapters exist: `FakeModel` (scripted, offline) and `OpenAIChatModel` (any server that speaks Chat Completions).

## Diagram

```
 runtime (M5)
   │ ModelRequest (our types: content blocks, ToolSpec, our call IDs)
   ▼
 OpenAIChatModel
   │ to_payload()          our blocks -> Chat Completions JSON (system message, tool_calls, role "tool")
   ▼
 HTTP POST {base_url}/chat/completions        (httpx; OpenAI, Kimi, DeepSeek, Qwen, Ollama, vLLM…)
   │
   ├─ error status / network failure ─► to_error() ─► RateLimited · ProviderUnavailable · ModelTimeout
   │                                                  · AuthFailed · ContextTooLong · BadRequest
   ▼
 from_completion()         JSON -> ModelResponse (our call IDs minted here)
 or _StreamState.feed()    server-sent events -> TextDelta, ToolUseStart, ToolArgsDelta… -> ResponseComplete
```

## Files

| File | Holds |
|---|---|
| [adapters/models/fake.py](../../src/agentreins/adapters/models/fake.py) | `FakeModel` and `stream_events()` |
| [adapters/models/openai_compat.py](../../src/agentreins/adapters/models/openai_compat.py) | `OpenAIChatModel`, the translations, stream parsing, error mapping |
| [ports/model.py](../../src/agentreins/ports/model.py) | The `ModelAdapter` port (and optional `TokenCounter`) |
| [tests/contract/test_model_adapter_contract.py](../../tests/contract/test_model_adapter_contract.py) | Rules every adapter must pass |
| [tests/recorded/](../../tests/recorded/) | Real OpenAI responses, replayed offline |
| [tests/live/test_openai_live.py](../../tests/live/test_openai_live.py) | Real calls, `pytest -m live` only |

## Walkthrough: one tool call, there and back

**1. The request.** The runtime asks: user says *"What's the weather in Paris?"*, tools `[get_weather]`. `to_payload` ([openai_compat.py:164](../../src/agentreins/adapters/models/openai_compat.py#L164)) builds the JSON body: `system` becomes the first message, each `ToolSpec` becomes a `{"type": "function", …}` entry, `max_tokens`/`temperature`/`stop` are copied, and `provider_options` are merged last so they can override anything.

**2. The reply.** OpenAI answers with `tool_calls: [{"id": "call_kcxj…", "function": {"name": "get_weather", "arguments": "{\"city\":\"Paris\"}"}}]`. `from_completion` ([openai_compat.py:265](../../src/agentreins/adapters/models/openai_compat.py#L265)) turns it into a `ToolUseBlock` with:

- `id`: a **new agentreins ID** (UUIDv7), stable across providers and resumes;
- `provider_id`: `"call_kcxj…"`, OpenAI's own ID, kept for the way back;
- `arguments`: the parsed dict. If the JSON is broken, or not an object, the block keeps `raw_arguments` and a `parse_error` instead of failing ([openai_compat.py:352](../../src/agentreins/adapters/models/openai_compat.py#L352)); the harness turns that into an error the model sees.

`finish_reason: "tool_calls"` becomes `stop_reason: "tool_use"`.

**3. The result goes back.** Next turn, the request holds the assistant message with that `ToolUseBlock`, then a user message with a `ToolResultBlock(tool_use_id=<our ID>)`. Chat Completions wants something else: the assistant's `tool_calls`, then one `{"role": "tool", "tool_call_id": "call_kcxj…"}` message per result. `_assistant_message` ([openai_compat.py:208](../../src/agentreins/adapters/models/openai_compat.py#L208)) remembers *our ID → provider ID* while writing `tool_calls`; `_user_messages` ([openai_compat.py:230](../../src/agentreins/adapters/models/openai_compat.py#L230)) uses that map for `tool_call_id`, and puts tool messages **before** any user text, because they must directly follow the assistant's calls.

**Streaming** goes through `_StreamState` ([openai_compat.py:380](../../src/agentreins/adapters/models/openai_compat.py#L380)). Each `data:` line is one chunk: text pieces become `TextDelta`, `reasoning_content` pieces `ReasoningDelta`, the first piece of a tool call (with its name) `ToolUseStart` with a freshly minted ID, later pieces `ToolArgsDelta` with the same ID. At the end, `finish()` builds the full response with the **same** builder `get_response` uses, so both paths can't drift apart. The request asks for usage in the stream (`stream_options.include_usage`), so token counts match too.

## Guarantees

| Promise | Proven by |
|---|---|
| Streamed and non-streamed calls give the same final response, for every adapter | [test_stream_and_get_response_agree](../../tests/contract/test_model_adapter_contract.py#L85) |
| A stream ends with exactly one complete response | [test_stream_ends_with_exactly_one_complete_response](../../tests/contract/test_model_adapter_contract.py#L93) |
| Deltas add up to the final response; streamed tool IDs match the final ones | [test_deltas_add_up_to_the_final_response](../../tests/contract/test_model_adapter_contract.py#L99) |
| Every tool call gets a unique agentreins ID; the provider's ID is kept | [test_tool_calls_get_our_own_ids](../../tests/unit/adapters/test_openai_compat.py#L192) |
| Tool results find their way back to the provider's IDs, in the order it requires | [test_tool_round_trip_uses_provider_ids_and_puts_results_first](../../tests/unit/adapters/test_openai_compat.py#L69) |
| Broken tool arguments are kept and flagged, never fatal | [test_bad_tool_arguments_are_kept_and_flagged](../../tests/unit/adapters/test_openai_compat.py#L210) |
| Every provider failure becomes a normalized error, streamed or not | [test_errors_are_normalized](../../tests/unit/adapters/test_openai_compat.py#L367), [test_stream_errors_are_normalized](../../tests/unit/adapters/test_openai_compat.py#L380) |
| The adapter still sends exactly what it sent when the real responses were recorded, and still parses them | [test_replay](../../tests/recorded/test_openai_recorded.py#L30) |
| Recordings hold no API key | [test_recordings_contain_no_secrets](../../tests/recorded/test_openai_recorded.py#L57) |

Error mapping:

| Provider says | We raise | Retryable |
|---|---|---|
| 429 | `RateLimited`, with `retry_after` from the header | yes |
| 5xx, connection failure, invalid or empty response | `ProviderUnavailable` | yes |
| 408, or our request timeout (120 s default) | `ModelTimeout` | yes |
| 401, 403 | `AuthFailed` | no |
| 4xx mentioning the context length | `ContextTooLong` | no |
| other 4xx | `BadRequest` | no |

## Three kinds of model tests

| Kind | Where | Needs network | What it catches |
|---|---|---|---|
| **Unit + contract** | `tests/unit/adapters/`, `tests/contract/` | no | Translation logic, every error path, the port's rules. Uses hand-built responses ([openai_fakes.py](../../tests/openai_fakes.py)). |
| **Recorded** | `tests/recorded/` | no | Drift from reality: real OpenAI responses, saved once, replayed on every test run. |
| **Live** | `tests/live/` | yes, with the key in `.env` | Provider changes. `pytest -m live`; `AGENTREINS_RECORD=1 pytest -m live` also refreshes the recordings. |

Recordings save the request body and the response body only, never headers, so the API key cannot end up in the repo.

## Design choices

| Choice | Alternatives | Why this one | Others |
|---|---|---|---|
| **HTTP directly with httpx** | The `openai` SDK | One small dependency (in the `providers` extra) instead of a vendor SDK; full control over the wire format | OpenAI Agents SDK and Pydantic AI use the `openai` SDK |
| **One Chat Completions adapter for many providers** | One adapter per provider | Kimi, DeepSeek, Qwen, Ollama, vLLM and most gateways speak it; change `base_url` | Pydantic AI's OpenAI model takes a provider setting: same idea |
| **Our own call IDs, minted by the adapter** | Use the provider's ID | Stable across providers and resumes; basis of the idempotency key (ADR-0001) | |
| **Recorded tests as plain JSON, replayed with httpx's mock transport** | `vcrpy` cassettes; hand-written responses only | No new dependency; files are readable in review; real data, not guesses | |
| **`reasoning_content` read, never sent back** | Ignore it | DeepSeek, Qwen and vLLM return it; Chat Completions providers do not accept it back | |
| **Context window as a setting** (default 128k) | Built-in model table; required setting | Tables go stale and can't know local models | |
| **The adapter never retries** | Retry inside the adapter | One retry policy for all providers, every attempt recorded (ADR-0002 D5) | OpenAI SDK retries internally by default |

## Extending it

**Another OpenAI-compatible provider:** no code needed.

```python
OpenAIChatModel(base_url="http://localhost:11434/v1")  # Ollama, no key
OpenAIChatModel(base_url="https://api.deepseek.com/v1", api_key=deepseek_key)
OpenAIChatModel(max_context_tokens=1_000_000)  # a long-context model
```

**A provider with a different API** (Anthropic Messages, Gemini): write a new adapter with `capabilities`, `get_response` and `stream_response`. Mint our own IDs for tool calls and keep the provider's in `provider_id`; map errors to the six normalized ones; build the streamed final response with the same code as the non-streamed one. Then add it to the `ADAPTERS` dict in [test_model_adapter_contract.py](../../tests/contract/test_model_adapter_contract.py).

**Testing your agent:** script the model instead of calling one.

```python
model = FakeModel(
    [
        FakeModel.call("get_stock", {"sku": "W1"}),  # turn 1: the model calls a tool
        FakeModel.reply("There are 7 in stock."),  # turn 2: it answers
    ]
)
# after the run: model.requests holds exactly what the agent sent each turn
```

## Known limits

- **`max_tokens` is sent as `max_tokens`.** Newer OpenAI reasoning models (`gpt-5*`, `o*`) reject it and want `max_completion_tokens`. Workaround: leave `max_tokens` unset and pass `provider_options={"max_completion_tokens": 500}`. A cleaner option can come when the runtime sets limits (M5).
- **`stop_sequence` is never reported.** Chat Completions says `stop` both for a normal end and for a stop sequence, so both become `end_turn`.
- **Tool results cannot carry images** in Chat Completions; an image in a tool result is replaced by a note.
- **Tool errors are marked in text.** Chat Completions has no error flag on tool messages, so an error result is sent as `"Error: …"`.
- **No exact token counting.** There is no `count_tokens`; the context manager will estimate (ADR-0002 D9).
- **`images` defaults to off.** Set `images=True` for models that accept images; the core then allows image blocks (checked in M5).
