# ADR-0003: ToolSource port

- **Status:** accepted (architecture step 3). Provisional until the Python-function and MCP sources exercise it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) C2, D1, guarantees #1 and #2

## Context

A ToolSource supplies tools to an agent: Python functions, MCP servers, later other agents. Every tool, whatever its source, is executed only through the tool harness (validate → policy → approval → credentials → execute → result). The interface is modelled on MCP's concepts (D1).

## Decisions

### D1. Methods

```python
class ToolSource(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call(self, call: ToolCall, context: ToolContext) -> ToolResult: ...
    async def close(self) -> None: ...
```

A source can also signal that its tool list changed (needed for MCP); the exact mechanism is decided when the MCP source is built.

### D2. ToolSpec

| Field | Meaning |
|---|---|
| `name`, `description` | What the model sees |
| `input_schema` | JSON Schema of the arguments |
| `effect` | `read_only` / `idempotent` / `side_effecting` |
| `timeout_seconds` | Maximum execution time (default 300 s) |
| `requires` | Credential needs, e.g. `["erp"]` (ADR-0008) |

MCP tools default to `side_effecting` unless configured otherwise. MCP's own annotations are hints from an external program and are not trusted. Python tools made with `@tool` also default to `side_effecting` (decided 2026-11-20): an undeclared tool asks for approval under the default policy rather than running freely.

### D3. ToolContext

What a tool receives at runtime:

| Field | Meaning |
|---|---|
| `principal` | Who the run acts for |
| `credentials` | From the CredentialProvider, scoped to the principal: one entry per need declared in `ToolSpec.requires` (e.g. `{"erp": …}`) |
| `run_id` | The current run |
| `cancellation` | Signal that the run is being cancelled |
| `idempotency_key` | Stable key for this tool call; the same across retries and resumes |

A side-effecting tool should pass `idempotency_key` to the real system (for example an ERP API), so that a repeated call is recognized and ignored there. This is how "never runs twice" holds end to end, not just inside agentreins.

### D4. Optional argument validation (decided 2026-11-20, M3)

```python
@runtime_checkable
class ArgumentValidator(Protocol):
    async def validate(self, name: str, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]: ...
```

Policy must see checked arguments (ADR-0004 D2), but the core cannot depend on a JSON Schema library. So a source may implement `validate()`: it returns the cleaned arguments or raises `InvalidToolArguments`. The Python source does, with pydantic (full checks and type conversion). Sources without it, such as MCP servers, get the harness's built-in basic check (`type`, `properties`, `required`, `additionalProperties: false`, `items`, `enum`). Rejected: only the basic check for every source (constraints like "quantity > 0" would be enforced only after policy had already allowed the call).

### D5. Harness phases (M3)

The harness has three phases so the runtime can write events in between and the harness never touches the log:

```text
check(block)      -> Rejected | NeedsApproval | Ready     validate, then policy
prepare(ready)    -> Rejected | Prepared                  fetch credentials (after any approval wait)
(runtime writes tool.call.started)
execute(prepared) -> Completed | Failed                   run, with timeout
```

`Ready` and `Prepared` carry a token only the harness that made them can create, so no tool can be run without passing validation and policy. A credential value echoed back by a tool, in its result or its error, is replaced with `***` before it can reach the log. The idempotency key is `"{run_id}:{call_id}"`.

## Comparison

To be completed when the Python-function source is built: compare with OpenAI Agents SDK `FunctionTool` and the MCP `tools/list` and `tools/call` methods.
