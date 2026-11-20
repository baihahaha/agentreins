# 03 Tools: `@tool`, sources, registry, harness, policy, credentials

## What it does

A tool is anything the model can ask the agent to do. Tools come from **tool sources** (Python functions today, MCP servers in M8), are collected in a **registry**, and are run only by the **harness**, which validates the arguments, asks **policy**, fetches **credentials** and runs the tool with a timeout. The model only *requests* a call; the harness decides whether it happens.

## Diagram

```text
 @tool functions ─► PythonToolSource ─┐
 MCP server (M8) ─► McpToolSource ────┼─► ToolRegistry ─► ToolHarness(registry, policy, credentials)
 your own        ─► YourToolSource ───┘   names unique

 ToolUseBlock from the model
   │
   ▼  check()     unknown tool? ── bad JSON? ── validate arguments ── Policy.decide()
   │              └────────────── Rejected ───────────────┘             │
   │                                                Allow ─ Deny ─ RequireApproval
   ▼                                                 Ready  Rejected NeedsApproval ─► human (M7)
   ▼  prepare()   CredentialProvider.get() for each need ─► Prepared  (or Rejected)
   │
   │  runtime writes tool.call.started
   ▼  execute()   source.call() under a timeout ─► Completed | Failed   (secrets scrubbed)
```

## Files

| File | Holds |
|---|---|
| [adapters/tool_sources/python.py](../../src/agentreins/adapters/tool_sources/python.py) | `@tool`, `FunctionTool`, `PythonToolSource` |
| [ports/tool_source.py](../../src/agentreins/ports/tool_source.py) | `ToolSource` port, optional `ArgumentValidator` |
| [tools/registry.py](../../src/agentreins/tools/registry.py) | `ToolRegistry`: name to (spec, source) |
| [tools/harness.py](../../src/agentreins/tools/harness.py) | `ToolHarness` and its outcomes |
| [tools/schema_check.py](../../src/agentreins/tools/schema_check.py) | Basic argument check for sources without `validate()` |
| [adapters/policies/default.py](../../src/agentreins/adapters/policies/default.py) | `DefaultPolicy`: reads allowed, side effects need approval |
| [adapters/credentials/env.py](../../src/agentreins/adapters/credentials/env.py) | `EnvCredentialProvider`: need `erp` reads `AGENTREINS_CRED_ERP` |

## Walkthrough: from a function to a finished call

**1. Define the tool.**

```python
@tool(requires=["erp"])  # effect not given: side_effecting (safe default)
async def create_po(sku: str, qty: int, ctx: ToolContext) -> dict:
    """Create a purchase order in the ERP."""
    ...
```

`_build` ([python.py:130](../../src/agentreins/adapters/tool_sources/python.py#L130)) reads the signature: the name from the function, the description from the docstring (required, because the model reads it), and a pydantic model from the type hints with `extra="forbid"`. Its JSON Schema becomes `ToolSpec.input_schema`. The `ctx: ToolContext` parameter is left out of the schema: the harness fills it in.

**2. Register it.** `ToolRegistry.from_sources([PythonToolSource([create_po, …])])` ([registry.py:42](../../src/agentreins/tools/registry.py#L42)) asks each source for its specs. Two tools with the same name, even from different sources, is an error: the model only sees names.

**3. The model asks** `create_po(sku="W1", qty="2")`. The runtime passes the `ToolUseBlock` to `check()` ([harness.py:135](../../src/agentreins/tools/harness.py#L135)):

- unknown name: `Rejected("unknown_tool", "Unknown tool … Available: …")`;
- unparseable JSON: `Rejected("invalid_arguments", …)`;
- **validate** ([harness.py:235](../../src/agentreins/tools/harness.py#L235)): the Python source has `validate()`, so pydantic checks and converts: `qty="2"` becomes `2`. A source without `validate()` (MCP) gets the basic check in `schema_check.py`;
- **policy** ([harness.py:248](../../src/agentreins/tools/harness.py#L248)) sees the *cleaned* arguments, principal, run and usage. `DefaultPolicy` answers `RequireApproval` because `create_po` is side-effecting. If the policy raises or takes over 10 s, the answer is `Deny("policy unavailable")`.

Result: `NeedsApproval`. In M7 the runtime pauses and asks a human. Say they approve, or the policy was `DefaultPolicy(allow=["create_po"])`; the outcome is `Ready`.

**4. `prepare()`** ([harness.py:175](../../src/agentreins/tools/harness.py#L175)) fetches `erp` credentials for this principal, **after** any approval wait, so no credential is held while a human decides (ADR-0008 D3). It builds the `ToolContext` with the idempotency key `"{run_id}:{call_id}"`. If the provider fails: `Rejected("credentials_unavailable", …)`; the tool never runs, and the provider's message is not shown (it might contain a secret).

**5. The runtime writes `tool.call.started`.** Now the intent is on disk.

**6. `execute()`** ([harness.py:208](../../src/agentreins/tools/harness.py#L208)) calls the source under `asyncio.timeout(spec.timeout_seconds)` (300 s by default). Sync functions run in a worker thread. Outcomes:

- returned: `Completed(result)`; `str` becomes text, `None` becomes `"(no output)"`, anything else becomes JSON;
- raised: `Failed("ValueError: bad sku")`;
- too slow: `Failed("timed out after 300 s", timed_out=True)`.

Before returning, any credential value that appears in the result text or error message is replaced with `***` ([harness.py:274](../../src/agentreins/tools/harness.py#L274)).

### Why nothing can skip a phase

`execute` only accepts a `Prepared`, which only `prepare` creates from a `Ready`, which only `check` creates after `Allow`. Each carries a private token known only to the harness that made it ([harness.py:257](../../src/agentreins/tools/harness.py#L257)), so a hand-built `Ready` or one from another harness is refused.

## Guarantees

All in [test_harness.py](../../tests/unit/tools/test_harness.py) unless noted:

| Promise | Proven by |
|---|---|
| Invalid arguments never reach policy | [test_invalid_arguments_never_reach_policy](../../tests/unit/tools/test_harness.py#L129) |
| Policy sees cleaned arguments | [test_policy_sees_cleaned_arguments_and_context](../../tests/unit/tools/test_harness.py#L140) |
| Read-only tools go through policy too | [test_read_only_tools_also_go_through_policy](../../tests/unit/tools/test_harness.py#L156) |
| Policy failure fails closed (or fails the run, if configured) | [test_policy_failure_denies_by_default](../../tests/unit/tools/test_harness.py#L171), [test_policy_failure_can_fail_the_run](../../tests/unit/tools/test_harness.py#L177) |
| Missing credentials: rejected, tool never runs | [test_missing_credentials_reject_without_running](../../tests/unit/tools/test_harness.py#L197) |
| Stable idempotency key | [test_prepare_builds_context_with_stable_idempotency_key](../../tests/unit/tools/test_harness.py#L186) |
| Tool errors and timeouts become `Failed`, never crash the run | [test_tool_exception_becomes_failed](../../tests/unit/tools/test_harness.py#L222), [test_timeout](../../tests/unit/tools/test_harness.py#L238) |
| Credentials never reach a result or error | [test_credentials_are_scrubbed_from_results_and_errors](../../tests/unit/tools/test_harness.py#L250) |
| No phase can be skipped or forged | [test_cannot_execute_without_check](../../tests/unit/tools/test_harness.py#L263), [test_ready_from_another_harness_is_refused](../../tests/unit/tools/test_harness.py#L277) |
| Non-Python sources still get argument checks | [test_source_without_validate_gets_the_basic_check](../../tests/unit/tools/test_harness.py#L339) |
| Defaults by effect class | [test_policy_and_credentials.py](../../tests/unit/adapters/test_policy_and_credentials.py) |

## Design choices

| Choice | Alternatives | Why this one | Others |
|---|---|---|---|
| **Harness in three phases**, returning values | One `run_tool()` that also writes events | The runtime writes `tool.call.started` between `prepare` and `execute`; the harness never touches the log, so it is testable alone | |
| **Validate before policy** | Policy on raw arguments | Policy decides on clean, typed values ("qty > 10000" works) (ADR-0004 D2) | |
| **Optional `validate()` on sources** | Basic check only; a JSON Schema library | Full pydantic checks for Python tools, no new core dependency (ADR-0003 D4) | |
| **`side_effecting` by default** | `effect` required | Safe by default (guarantee #2): an undeclared tool asks for approval | OpenAI Agents SDK, Pydantic AI have no effect classes |
| **Policy for every call** | Allow-lists only | Rules can depend on arguments, principal and usage | Claude Agent SDK: allowed tools + permission callback |
| **Credentials per call, per principal** | One shared key | The agent never has more power than the user it acts for (ADR-0008) | AWS AgentCore Identity, OAuth token exchange |
| **Decorator in the adapter** | Decorator in `tools/` | The layer rule: adapters cannot import engines (see [ARCHITECTURE.md](../../ARCHITECTURE.md)) | |

## Extending it

There are three ways to reach a tool, from simplest to most general:

1. **Wrap it in `@tool`.** REST API, SQL, CLI, SDK: a function that makes the call. Use `ctx.credentials["erp"].reveal()` for the secret and send `ctx.idempotency_key` to the real system, so it can ignore a repeated call.
2. **MCP server** (M8): point agentreins at it; its tools default to `side_effecting`.
3. **Your own `ToolSource`:** implement `list_tools`, `call` and `close` (and optionally `validate`). Example: `SchemaOnlySource` at the end of [test_harness.py](../../tests/unit/tools/test_harness.py#L315). Use this for families of tools, e.g. one per operation in an OpenAPI spec.

**Your own policy:** one method, `async def decide(request) -> Allow | Deny | RequireApproval`. Add `visible_tools()` to hide tools the principal can never use. Return a reason the model can understand: it is shown to it.

**Your own credential provider:** `async def get(principal, name) -> Credentials`. Fetch per principal (STS role, OAuth token exchange), cache and refresh inside the provider; never put the secret in an error message.

## Known limits

- **A sync tool keeps running after a timeout.** It runs in a thread, and Python cannot kill threads. The run moves on; the thread finishes in the background. Write long-running tools as `async`, and check `ctx.cancellation`.
- **Scrubbing catches exact matches in text only.** A secret that a tool encodes (base64), splits, or puts in an image is not caught. Tools should not echo secrets; this is a safety net.
- **The basic schema check is basic.** Only `type`, `properties`, `required`, `additionalProperties: false`, `items` and `enum`. Other keywords (`minimum`, `pattern`, `$ref`…) are ignored, not enforced.
- **Approvals are not wired yet.** `NeedsApproval` is returned; pausing and resuming the run comes in M7.
- **The registry is fixed once built.** MCP servers can change their tool list; how that is signalled is decided with the MCP source (M8).
