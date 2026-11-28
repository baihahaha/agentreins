# 05 Runtime: the agent loop and the public `Agent`

## What it does

`Agent` is what users create. It picks the model, collects the tools, plugs in default adapters for everything not given, and builds a `Runtime`. `Runtime.run(task)` is one run: it asks the model, runs the tools it requests through the harness, feeds the results back, and repeats until the model answers. Every step is written to the event log *before* the next one, so the log alone explains the run. Budgets, retries and hooks live here; trimming the conversation lives in the context manager.

## Diagram

```
 Agent("openai:gpt-4.1-mini", tools=[...])          public API: chooses adapters
   │ first run: _build()
   ▼
 Runtime(model, harness, ledger, context, hooks, budget, retry)
   │ run(task)
   ▼
 run.started
 ┌─► check budget (steps, tokens, wall time) ─────────────────────► run.failed (budget)
 │   project_messages(log) → ContextManager.select → ModelRequest
 │   model.requested → model call ── error ──► model.failed → retry? ── no ─► run.failed
 │   model.responded                              │ yes: wait 1 s, 2 s… ─┘ (back to model call)
 │   no tool calls? ───────────────────────────────────────────────► run.completed
 │   tool.call.requested × n
 │   harness.check × n ── needs approval ──────────────────────────► run.failed (until M7)
 │   rejected → tool.call.rejected
 │   harness.prepare → tool.call.started × n   (one batch: all intents on disk first)
 │   execute in parallel → tool.call.completed / failed (as each finishes)
 └───┘
```

## Files

| File | Holds |
|---|---|
| [agent.py](../../src/agentreins/agent.py) | `Agent`: model resolution, default adapters, `run`, `run_sync`, `close` |
| [runtime/loop.py](../../src/agentreins/runtime/loop.py) | `Runtime`, the per-run `_Run`, `RetryPolicy`, `ModelSettings`, `RunResult` |
| [context/manager.py](../../src/agentreins/context/manager.py) | `ContextManager`, `estimate_tokens` |
| [adapters/context_strategies/keep_all.py](../../src/agentreins/adapters/context_strategies/keep_all.py) | `KeepAll`, the default strategy |
| [runtime/hooks.py](../../src/agentreins/runtime/hooks.py) | `HookDispatcher` |
| [examples/](../../examples/) | Runnable examples (offline ones run in CI) |

## Walkthrough: "How many W1 do we have?"

```python
agent = Agent("openai:gpt-4.1-mini", instructions="You are a stock clerk.", tools=[get_stock])
result = await agent.run("How many W1 do we have?")
```

**1. Building the agent.** `_resolve_model` ([agent.py:269](../../src/agentreins/agent.py#L269)) turns `"openai:gpt-4.1-mini"` into an `OpenAIChatModel` plus the name `gpt-4.1-mini`. Nothing else happens yet. On the first run, `_build` ([agent.py:234](../../src/agentreins/agent.py#L234)) groups `@tool` functions into one `PythonToolSource`, builds the registry (asking each source for its tools), opens the default SQLite store, and creates the `Runtime`. `Agent` is the only place that names adapters; the runtime below it only knows ports.

**2. Starting the run.** `_Run.execute` ([loop.py:224](../../src/agentreins/runtime/loop.py#L224)) records `run.started`: the task, model, visible tools, budget and principal (`Principal(id="local")` if none was given). This is the whole loop:

```python
while True:
    self.check_budget()
    response = await self.model_turn(tools)
    calls = [b for b in response.message.content if isinstance(b, ToolUseBlock)]
    if not calls:
        return await self.complete(response.message)
    await self.tool_turn(calls)
```

**3. A model turn** ([loop.py:306](../../src/agentreins/runtime/loop.py#L306)). The conversation is rebuilt from the log (`project_messages`), and the context manager passes it through unchanged while it fits in 80% of the model's window. `model.requested` records a fingerprint (SHA-256) of the exact request. The model answers with a call to `get_stock(sku="W1")`; `model.responded` records it, and the loop continues with the reply *as stored*, so a redactor's changes apply to what the model sees next.

If the provider fails, `model.failed` records the attempt. Retryable errors wait (1 s, 2 s…, or the provider's `retry_after`, capped at 30 s) and try again, at most 3 attempts. `ContextTooLong` gets one retry only if the strategy can shrink the request.

**4. A tool turn** ([loop.py:454](../../src/agentreins/runtime/loop.py#L454)). For every call: `tool.call.requested`, then the harness checks it (validation, policy). If any call needs approval, the run stops before anything runs. Rejected calls are recorded; the rest get credentials. Then **all** `tool.call.started` records are written in one batch, and only after that do the tools run, in parallel (`asyncio.gather`). Each outcome is recorded the moment its tool finishes.

**5. Recording.** Events need a `seq` that is only known when they are written. `ev(EventClass, **fields)` ([loop.py:201](../../src/agentreins/runtime/loop.py#L201)) binds all other fields at once; `record()` ([loop.py:208](../../src/agentreins/runtime/loop.py#L208)) assigns the next `seq` values and appends under a lock, since parallel tools finish concurrently. Each stored event then goes to the hooks.

**6. The answer.** On the next turn the model sees the tool result (`"7"`) and answers in text. No tool calls: `run.completed` is recorded with the answer and the total usage, and `run` returns a `RunResult` (`output`, `message`, `usage`, `steps`, `run_id`). Had the run ended without an answer, `RunError` would be raised, with the reason and the `run_id` to look it up in the log.

### Structured output

With `Agent(..., output_type=Order)` the loop changes in one place, `output_turn` (in [loop.py](../../src/agentreins/runtime/loop.py)): the model is also given a hidden `final_result` tool whose arguments are the fields of `Order` ([output.py](../../src/agentreins/runtime/output.py)).

| The model's reply | What happens |
|---|---|
| Calls `final_result` with a valid answer | `run.completed` with `structured` set; `result.output` is the `Order`. Other tool calls in the same reply are rejected (`run_ended`) and never run |
| Calls `final_result` with an invalid answer | Rejected as `invalid_arguments`; the model sees the validation errors and tries again (a new step). Other tool calls in the reply run normally |
| Answers in plain text | The runtime adds a reminder (`message.added`, origin `runtime`) and asks again (a new step) |
| Calls only normal tools | A normal tool turn |

`max_steps` bounds a model that never gets it right. `Agent` is generic, so `result.output` has the type of `output_type` in your editor (`str` without it).

## Try it

Run from the repo root (offline, free). Change the inputs and run again.

**Try:** the first example.

```bash
uv run python examples/01_hello_tool.py
```

**Try:** watch a run as it happens, with a hook, then print its event log. Change the script to see other paths: put a `ProviderUnavailable("down")` first in the list (a retry, after a 1 s wait), or use `create_po` (the run stops: approval needed).

```bash
uv run python - <<'EOF'
import asyncio
from agentreins import Agent, tool
from agentreins.adapters.event_stores.in_memory import InMemoryEventStore
from agentreins.testing import FakeModel

@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Units on hand."""
    return {"W1": 7, "W2": 3}[sku]

class Show:
    async def on_event(self, event):
        if hasattr(event, "seq"):
            print(f"  event {event.seq:2} {event.type}")

both = FakeModel.call("get_stock", {"sku": "W1"})
both = both.model_copy(update={"message": both.message.model_copy(update={"content": [
    *both.message.content, *FakeModel.call("get_stock", {"sku": "W2"}).message.content]})})
model = FakeModel([both, FakeModel.reply("W1: 7, W2: 3.")])

async def main():
    store = InMemoryEventStore()
    agent = Agent(model, tools=[get_stock], store=store, hooks=[Show()])
    result = await agent.run("Stock of W1 and W2?")
    print("answer:", result.output, "| steps:", result.steps)
    print("turn 2 sent to the model:", [(m.role, [b.type for b in m.content]) for m in model.requests[1].messages])
asyncio.run(main())
EOF
```

**Try:** every run ends. A model that keeps calling tools is stopped by `max_steps`, and the reason is in the log.

```bash
uv run python - <<'EOF'
from agentreins import Agent, Budget, RunError, tool
from agentreins.adapters.event_stores.in_memory import InMemoryEventStore
from agentreins.testing import FakeModel

@tool(effect="read_only")
def ping() -> str:
    """Ping."""
    return "pong"

agent = Agent(FakeModel([FakeModel.call("ping")] * 10), tools=[ping], store=InMemoryEventStore(), budget=Budget(max_steps=3))
try:
    agent.run_sync("loop forever")
except RunError as e:
    print("stopped:", e.reason, "|", e)
EOF
```

**Try:** structured output, with the second example. The scripted model first gives an invalid answer (`quantity=-9`), gets the validation error back, and corrects it.

```bash
uv run python examples/02_structured_output.py
```

**Try:** a model that answers in plain text gets reminded, and the reminder is in the log.

```bash
uv run python - <<'EOF'
import asyncio
from pydantic import BaseModel
from agentreins import Agent
from agentreins.adapters.event_stores.in_memory import InMemoryEventStore
from agentreins.testing import FakeModel

class City(BaseModel):
    name: str
    country: str

model = FakeModel([FakeModel.reply("It's Paris, in France."), FakeModel.call("final_result", {"name": "Paris", "country": "FR"})])

async def main():
    store = InMemoryEventStore()
    result = await Agent(model, output_type=City, store=store).run("Capital of France?")
    print("output:", repr(result.output))
    for e in await store.read(result.run_id):
        extra = f'  "{e.message.text}"' if e.type == "message.added" else ""
        print(f"  {e.seq:2} {e.type}{extra}")
asyncio.run(main())
EOF
```

## Guarantees

| Promise | Proven by |
|---|---|
| Every step is in the log, in order, with no gaps; the log always rebuilds a valid conversation | `assert_valid_log`, run after every test in [test_loop.py](../../tests/unit/runtime/test_loop.py) |
| Tools of one turn really run in parallel, and all intent records are written before any runs | [test_parallel_tool_calls_really_run_together](../../tests/unit/runtime/test_loop.py#L199) |
| Tool results reach the model in call order, not completion order | same test |
| A tool needing approval stops the run before anything runs | [test_approval_needed_stops_the_run_cleanly](../../tests/unit/runtime/test_loop.py#L302) |
| Rejected, failed and credential-less calls are recorded, and the model is told | [test_denied_call_is_rejected_and_the_model_is_told](../../tests/unit/runtime/test_loop.py#L254), [test_failing_tool_is_recorded_and_the_run_continues](../../tests/unit/runtime/test_loop.py#L292), [test_missing_credentials_reject_the_call_and_the_run_continues](../../tests/unit/runtime/test_loop.py#L276) |
| Retryable errors are retried with backoff; each attempt is recorded | [test_retry_then_success](../../tests/unit/runtime/test_loop.py#L340), [test_retries_run_out](../../tests/unit/runtime/test_loop.py#L363) |
| Every run ends: step, token and wall-time limits | [test_max_steps](../../tests/unit/runtime/test_loop.py#L403), [test_max_tokens](../../tests/unit/runtime/test_loop.py#L413) |
| A tool that runs over budget finishes and is recorded before the run stops | [test_wall_time_runs_out_mid_tool_the_tool_finishes_first](../../tests/unit/runtime/test_loop.py#L424) |
| A cancelled run is recorded as cancelled | [test_cancelled_run_is_recorded](../../tests/unit/runtime/test_loop.py#L454) |
| Broken or hanging hooks never stop a run | [test_failing_and_hanging_hooks_never_stop_a_run](../../tests/unit/runtime/test_loop.py#L508) |
| One agent serves concurrent runs | [test_one_agent_many_concurrent_runs](../../tests/unit/test_agent.py#L143) |
| Every offline example runs | [test_examples.py](../../tests/unit/test_examples.py) |
| Structured answers are validated and typed; invalid ones are retried; nothing runs after a valid answer | [test_structured_output.py](../../tests/unit/test_structured_output.py) |

## Design choices

| Choice | Alternatives | Why this one | Others |
|---|---|---|---|
| **Write each step before the next** | Keep state in memory, save at the end | A crash at any point leaves a log that says exactly what happened (guarantee #1) | OpenAI Agents SDK keeps run items in memory; LangGraph saves a snapshot per step |
| **Parallel tools, intents first** | Run tools one after another | Faster when tools wait on networks, and still crash-safe | OpenAI Agents SDK and Pydantic AI also run tool calls concurrently |
| **Retries in the runtime** | Retries in each adapter or HTTP client | One policy for all providers; every attempt in the log and counted in budgets | The `openai` SDK retries internally by default |
| **Failed runs raise `RunError`** | Return a result with a status | An unchecked status could be mistaken for an answer | OpenAI Agents SDK raises `MaxTurnsExceeded`; Pydantic AI raises `UsageLimitExceeded` |
| **Budgets checked between steps** | Interrupt a tool mid-way | A half-run side effect is worse than a slightly late stop (REQUIREMENTS conflict rules) | |
| **Stream only when hooks are registered** | Always stream | One plain call per turn when nobody watches; same final response either way (contract test) | |
| **`Agent` in the public-API layer** | `Agent` in `runtime/` | The runtime may not import adapters, and `Agent` must choose default ones (layer rule) | |
| **`"provider:model"` strings and adapter objects** | Objects only | Short for the common case, full control when needed | Pydantic AI uses the same string style |

## Extending it

**Different defaults:** pass them in. Anything given replaces the default; the rest stay.

```python
Agent(
    OpenAIChatModel(base_url="http://localhost:11434/v1"),
    model_name="llama3",
    tools=[get_stock, create_po],
    policy=DefaultPolicy(allow=["create_po"]),
    store=SQLiteEventStore("/var/lib/myapp/agent.db"),
    budget=Budget(max_steps=10, max_tokens=50_000, max_wall_seconds=120),
    hooks=[MyTracingHook()],
)
```

**Watching a run live:** a hook gets every event and every streamed delta.

```python
class PrintAnswer:
    async def on_event(self, event):
        if event.type == "text_delta":
            print(event.text, end="", flush=True)
```

**Testing an agent:** script the model with `FakeModel` (from `agentreins.testing`) and use `InMemoryEventStore`; see [examples/01_hello_tool.py](../../examples/01_hello_tool.py).

## Known limits

- **Approval stops the run.** Pausing and resuming after a human decides arrives in M7.
- **No resume yet.** A crashed run stays in the log as unfinished; picking it up again (recovery, sessions, run keys in practice) is M6.
- **No cost budget.** `max_cost_usd` raises an error until agentreins knows model prices.
- **One model per agent.** Switching models mid-run (fallbacks) is not supported.
- **The default store is a file in the working directory** (`agentreins.db`). Pass `store=` to put it elsewhere, or `InMemoryEventStore()` in tests.
