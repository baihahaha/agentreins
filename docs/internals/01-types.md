# 01 Types: the shared vocabulary

## What it does

`agentreins.types` defines every data shape the framework passes around: messages, model requests and responses, tool specs and results, policy decisions, identity, and the events of the log. It is pure data with no behaviour beyond validation, and it depends on nothing but the standard library and pydantic. Every other layer imports it; it imports nothing else.

## Diagram

```text
                       ┌─────────── Message ───────────┐
                       │ role: user | assistant         │
                       │ content: [ContentBlock, …]     │
                       └───────────────┬────────────────┘
       TextBlock · ImageBlock · ToolUseBlock · ToolResultBlock · ReasoningBlock
                                       │ used by
   ┌───────────────────┬───────────────┼────────────────────┬──────────────────┐
ModelRequest /     ToolSpec, ToolCall,  PolicyRequest,      Events (run.*, model.*, tool.*)
ModelResponse      ToolResult,          Allow/Deny/         = envelope + these types
(model.py)         ToolContext          RequireApproval     (events.py)
                   (tools.py)           (policy.py)
```

## Files

| File | Holds |
|---|---|
| [_base.py](../../src/agentreins/types/_base.py) | `FrozenModel`: base of every model (frozen, unknown fields rejected) |
| [content.py](../../src/agentreins/types/content.py) | `Message` and the five content blocks |
| [model.py](../../src/agentreins/types/model.py) | `ModelRequest`, `ModelResponse`, `ModelCapabilities`, stream events |
| [tools.py](../../src/agentreins/types/tools.py) | `Effect`, `ToolSpec`, `ToolCall`, `ToolResult`, `ToolContext` |
| [policy.py](../../src/agentreins/types/policy.py) | `PolicyRequest` and the three decisions |
| [identity.py](../../src/agentreins/types/identity.py) | `Principal`, and `Credentials`, which cannot leak |
| [events.py](../../src/agentreins/types/events.py) | The event envelope, the 11 event types, `Event`, `RunRef` |
| [budget.py](../../src/agentreins/types/budget.py) | `Usage` (tokens) and `Budget` (limits; 25 steps by default) |
| [knowledge.py](../../src/agentreins/types/knowledge.py) | `Document` (retriever results), `MemoryItem` |
| [errors.py](../../src/agentreins/types/errors.py) | All agentreins exceptions; model errors carry `retryable` |
| [ids.py](../../src/agentreins/types/ids.py) | `new_id()`: UUIDv7 |

## Walkthrough: one tool-using turn, as data

**1. The user's message.** `Message.user("Order 2 widgets")` ([content.py:109](../../src/agentreins/types/content.py#L109)) is a `Message` with one `TextBlock`.

**2. The model's reply.** The adapter returns a `ModelResponse` ([model.py:39](../../src/agentreins/types/model.py#L39)) whose message holds text *and* a tool call in one list, which flat formats like Chat Completions cannot express directly:

```python
Message(
    role="assistant",
    content=[
        TextBlock(text="Let me check stock."),
        ToolUseBlock(id="0193…", provider_id="call_abc", name="get_stock", arguments={"sku": "W1"}),
    ],
)
```

`id` is agentreins' own call ID; `provider_id` keeps the provider's ID for mapping back (ADR-0001). If the provider sends unparseable JSON, the block keeps `raw_arguments` plus `parse_error` instead of failing ([content.py:34](../../src/agentreins/types/content.py#L34)); the harness turns that into an error the model sees.

**3. The tool result** goes back in a `user` message, as Anthropic does:

```python
Message(role="user", content=[ToolResultBlock(tool_use_id="0193…", content=[TextBlock(text="7")])])
```

`Message` checks that blocks fit the role: a user message cannot hold a `tool_use`, an assistant message cannot hold a `tool_result` ([content.py:101](../../src/agentreins/types/content.py#L101)).

**4. The same turn as events.** What is stored is not the messages but events: flat JSON, the envelope next to the type's own fields ([events.py:29](../../src/agentreins/types/events.py#L29)):

```json
{"event_id": "0193…", "run_id": "0192…", "seq": 3, "schema_version": 1,
 "timestamp": "2026-11-20T10:00:00Z", "type": "tool.call.completed",
 "call_id": "0193…", "result": {"content": [{"type": "text", "text": "7"}], "is_error": false},
 "duration_ms": 12.5}
```

`Event` ([events.py:174](../../src/agentreins/types/events.py#L174)) is a discriminated union: pydantic reads `type` and builds exactly `ToolCallCompleted`. The messages of step 1–3 are rebuilt from these events by the projection (see [02 Storage](02-storage.md)).

## Guarantees

| Promise | How | Proven by |
|---|---|---|
| Data cannot be changed after creation | `frozen=True` on every model | [test_messages_are_frozen](../../tests/unit/types/test_types_content.py#L60), [test_events_are_immutable](../../tests/unit/types/test_types_events.py#L134) |
| Typos in field names fail loudly | `extra="forbid"` | [test_unknown_fields_are_rejected](../../tests/unit/types/test_types_content.py#L66) |
| JSON reads back as the exact class | `type` discriminator on every union | [test_blocks_are_parsed_by_their_type_field](../../tests/unit/types/test_types_content.py#L52), [test_event_round_trips_through_the_union](../../tests/unit/types/test_types_events.py#L95) |
| Blocks match the message role | validator on `Message` | [test_blocks_must_match_role](../../tests/unit/types/test_types_content.py#L79) |
| Credentials cannot be printed, serialized, pickled or stored | `Credentials` is not pydantic; `repr` shows `***`; pickling raises | [test_credentials_cannot_be_serialized_or_copied](../../tests/unit/types/test_types_governance.py#L91), [test_credentials_cannot_enter_an_event](../../tests/unit/types/test_types_events.py#L147) |
| Timestamps are unambiguous | `AwareDatetime`: a time without a timezone is rejected | [test_naive_timestamp_is_rejected](../../tests/unit/types/test_types_events.py#L123) |

## Design choices

| Choice | Alternatives | Why this one | Others |
|---|---|---|---|
| **Content blocks** (`list[Block]` per message) | Flat messages with `tool_calls` (OpenAI Chat Completions) | Can hold text, tool calls, reasoning and images in one message; maps losslessly to every provider (ADR-0002 D3) | Anthropic, Gemini, OpenAI Responses, Pydantic AI use blocks |
| **Flat events**, one class per type | Nested `payload` object (Temporal, CloudEvents) | Simpler to read and write in Python; nesting pays off only for language-neutral wire formats (ADR-0001) | Anthropic API events, OpenAI Agents SDK items are flat |
| **UUIDv7** IDs | UUIDv4 (random), ULID (needs a library) | Time-sortable like ULID, standard UUID format, in the stdlib from Python 3.14 (a short fallback covers 3.11–3.13) | |
| **Own call ID** on every tool call | Use the provider's ID | Stable across providers and resumes; basis of the idempotency key | |
| **`Credentials` as a plain class** | A pydantic model with `SecretStr` | `SecretStr` can still be serialized on purpose; a non-pydantic class *cannot* be put in an event at all | |
| **`ToolContext` as a dataclass** | A pydantic model | It holds `Credentials` and a live `asyncio.Event`; it is never stored, so validation buys nothing | |

## Extending it

**Adding an event type** (e.g. `run.interrupted` in M7):

1. Add a class to [events.py](../../src/agentreins/types/events.py) with `type: Literal["run.interrupted"]`, past-tense name.
2. Add it to the `Event` union.
3. Decide what the projection does with it ([projections.py](../../src/agentreins/ledger/projections.py)); most bookkeeping events are ignored.
4. Add it to `one_of_each()` in [test_types_events.py](../../tests/unit/types/test_types_events.py) so the round-trip test covers it.
5. Update the event table in ADR-0001.

**Changing an existing event's fields:** stored events outlive code. Add new fields with defaults (old events still parse). For anything else, bump that type's `schema_version` and write a migration; old logs must stay readable (ADR-0005 D4).

## Known limits

- **Frozen is shallow.** You cannot assign `message.role = …`, but you can still call `message.content.append(…)`. Treat models as read-only; use `model_copy(update=…)` to change them.
- **No migrations yet.** `schema_version` is recorded (1 everywhere) but nothing reads it yet. The first real migration will add the mechanism.
- **UUIDv7 order within one millisecond** is random on Python < 3.14. Harmless: event order comes from `seq`, never from IDs or timestamps.
