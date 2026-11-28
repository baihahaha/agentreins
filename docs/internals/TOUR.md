# Hands-on tour

Read the code in order and try each part as you go. Every experiment is copy-paste: run it from the repo root. Everything is offline and free except the last step.

About 3 hours in total; each step stands alone, so it can be spread over several sessions.

| Step | Read | Try | Time |
|---|---|---|---|
| 0 | | Set up, run all tests | 5 min |
| 1 | The big picture | | 20 min |
| 2 | Types | Messages, events, credentials | 20 min |
| 3 | Storage | Save, conflict, rebuild the conversation | 25 min |
| 4 | Tools | `@tool`, the harness, the default policy | 30 min |
| 5 | Models | Fake model, translation to OpenAI, errors | 25 min |
| 6 | Runtime and `Agent` | A whole run, its event log, limits | 30 min |
| 7 | Structured output | A typed answer | 15 min |
| 8 | Live (optional) | The same with a real model | 10 min |

## 0. Set up

```bash
uv sync --all-extras          # install everything, including dev tools
uv run pytest -q              # all offline tests: should end with "passed"
```

Run one test file, or one test, while reading:

```bash
uv run pytest tests/unit/runtime/test_loop.py -v
uv run pytest tests/unit/runtime/test_loop.py -v -k parallel
```

## 1. The big picture

Read [README.md](README.md) in this folder: the layer picture (types → ports → engines → runtime → public API, adapters beside), then **One agent run, end to end**. Every later step is one box of that diagram.

## 2. Types: the shared vocabulary

**Read:** [01-types.md](01-types.md), then [content.py](../../src/agentreins/types/content.py) and [events.py](../../src/agentreins/types/events.py).

**Try:** a message, its JSON, and an event read back as its exact class.

```bash
uv run python - <<'EOF'
from pydantic import TypeAdapter
from agentreins.types.content import Message, ToolUseBlock
from agentreins.types.events import Event, ModelResponded
from agentreins.types.model import ModelResponse
from agentreins.types.budget import Usage

msg = Message(role="assistant", content=[ToolUseBlock(id="c1", name="get_stock", arguments={"sku": "W1"})])
print("JSON:", msg.model_dump_json())

event = ModelResponded(run_id="r1", seq=2, step=1, latency_ms=12,
    response=ModelResponse(message=msg, stop_reason="tool_use", usage=Usage(input_tokens=9), model="m"))
stored = TypeAdapter(Event).dump_json(event)
back = TypeAdapter(Event).validate_json(stored)
print("read back as:", type(back).__name__, "| same?", back == event)

from pydantic import ValidationError
try:
    Message(role="user", content=[ToolUseBlock(id="c1", name="x")])
except ValidationError as e:
    print("refused:", e.errors()[0]["msg"])
EOF
```

**Try:** credentials refuse to leak.

```bash
uv run python - <<'EOF'
import pickle
from agentreins.types.identity import Credentials

key = Credentials("erp", "s3cret-token")
print("printed:", key)                     # the secret is hidden
print("revealed:", key.reveal())           # only on purpose
try:
    pickle.dumps(key)
except TypeError as e:
    print("pickle:", e)
EOF
```

## 3. Storage: the event log

**Read:** [02-storage.md](02-storage.md), then [ledger.py](../../src/agentreins/ledger/ledger.py), [sqlite.py](../../src/agentreins/adapters/event_stores/sqlite.py) and [projections.py](../../src/agentreins/ledger/projections.py).

**Try:** save a run to SQLite, read it back after "restarting", and see a conflicting write refused.

```bash
uv run python - <<'EOF'
import asyncio, tempfile, os
from agentreins.adapters.event_stores.sqlite import SQLiteEventStore
from agentreins.types.content import Message
from agentreins.types.events import RunStarted, ModelRequested
from agentreins.types.identity import Principal
from agentreins.types.errors import ConflictError

async def main():
    path = os.path.join(tempfile.mkdtemp(), "tour.db")
    store = SQLiteEventStore(path)
    start = RunStarted(run_id="r1", seq=0, input=[Message.user("hi")], model="m", principal=Principal(id="ana"))
    await store.append("r1", [start], expected_seq=-1)
    await store.close()

    store = SQLiteEventStore(path)                       # like a new process
    print("after reopening:", [e.type for e in await store.read("r1")])
    ask = ModelRequested(run_id="r1", seq=1, step=1, message_count=1, input_fingerprint="f")
    await store.append("r1", [ask], expected_seq=0)       # writer A
    try:
        await store.append("r1", [ask], expected_seq=0)   # writer B, same position
    except ConflictError as e:
        print("second writer refused:", e)
    await store.close()

asyncio.run(main())
EOF
```

**Try:** rebuild the conversation from events. Tool results come back in call order, even though `b` finished first.

```bash
uv run python - <<'EOF'
from agentreins.ledger.projections import project_messages
from agentreins.types.budget import Usage
from agentreins.types.content import Message, ToolUseBlock
from agentreins.types.events import RunStarted, ModelResponded, ToolCallCompleted
from agentreins.types.identity import Principal
from agentreins.types.model import ModelResponse
from agentreins.types.tools import ToolResult

calls = Message(role="assistant", content=[ToolUseBlock(id="a", name="t"), ToolUseBlock(id="b", name="t")])
events = [
    RunStarted(run_id="r", seq=0, input=[Message.user("go")], model="m", principal=Principal(id="ana")),
    ModelResponded(run_id="r", seq=1, step=1, latency_ms=1,
        response=ModelResponse(message=calls, stop_reason="tool_use", usage=Usage(), model="m")),
    ToolCallCompleted(run_id="r", seq=2, call_id="b", result=ToolResult.text("B"), duration_ms=1),
    ToolCallCompleted(run_id="r", seq=3, call_id="a", result=ToolResult.text("A"), duration_ms=1),
]
for m in project_messages(events):
    print(m.role, [getattr(b, "tool_use_id", None) or getattr(b, "text", None) or b.type for b in m.content])
EOF
```

## 4. Tools: `@tool`, the harness, policy

**Read:** [03-tools.md](03-tools.md), then [python.py](../../src/agentreins/adapters/tool_sources/python.py) (the decorator) and [harness.py](../../src/agentreins/tools/harness.py) (start with its module docstring).

**Try:** what `@tool` builds from a plain function.

```bash
uv run python - <<'EOF'
import json
from agentreins import tool

@tool(effect="read_only")
def get_stock(sku: str, warehouse: str = "main") -> int:
    """Units on hand for a product SKU."""
    return 7

print("name:", get_stock.spec.name, "| effect:", get_stock.spec.effect)
print("what the model sees:", json.dumps(get_stock.spec.input_schema, indent=1))
print("still a normal function:", get_stock("W1"))
EOF
```

**Try:** one call through all three phases, and what the default policy does with a side effect.

```bash
uv run python - <<'EOF'
import asyncio
from agentreins import tool
from agentreins.adapters.credentials.env import EnvCredentialProvider
from agentreins.adapters.policies.default import DefaultPolicy
from agentreins.adapters.tool_sources.python import PythonToolSource
from agentreins.tools.harness import ToolHarness, Ready
from agentreins.tools.registry import ToolRegistry
from agentreins.types.content import ToolUseBlock
from agentreins.types.identity import Principal

@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Units on hand."""
    return 7

@tool                                   # no effect given: side_effecting
def create_po(sku: str, qty: int) -> str:
    """Create a purchase order."""
    return "PO-1"

async def main():
    registry = await ToolRegistry.from_sources([PythonToolSource([get_stock, create_po])])
    harness = ToolHarness(registry, DefaultPolicy(), EnvCredentialProvider())
    me = Principal(id="ana")

    checked = await harness.check(ToolUseBlock(id="c1", name="get_stock", arguments={"sku": "W1"}), principal=me, run_id="r1")
    print("1 check:  ", type(checked).__name__)
    assert isinstance(checked, Ready)
    prepared = await harness.prepare(checked, principal=me, run_id="r1")
    print("2 prepare:", type(prepared).__name__, "| idempotency key:", prepared.context.idempotency_key)
    print("3 execute:", await harness.execute(prepared))

    bad = await harness.check(ToolUseBlock(id="c2", name="create_po", arguments={"sku": "W1", "qty": "many"}), principal=me, run_id="r1")
    print("\nbad arguments:", bad)
    order = await harness.check(ToolUseBlock(id="c3", name="create_po", arguments={"sku": "W1", "qty": 2}), principal=me, run_id="r1")
    print("side effect:", type(order).__name__, "->", order.reason)

asyncio.run(main())
EOF
```

## 5. Models: talking to providers

**Read:** [04-models.md](04-models.md), then [fake.py](../../src/agentreins/adapters/models/fake.py) and [openai_compat.py](../../src/agentreins/adapters/models/openai_compat.py) section by section (`to_payload`, `from_completion`, `_StreamState`, `to_error`).

**Try:** our request, translated into what OpenAI receives. Note the provider's call ID `call_abc` (not ours), and the `tool` message placed before the user text.

```bash
uv run python - <<'EOF'
import json
from agentreins.adapters.models.openai_compat import to_payload
from agentreins.types.content import Message, TextBlock, ToolResultBlock, ToolUseBlock
from agentreins.types.model import ModelRequest

request = ModelRequest(model="gpt-4.1-mini", system="Be brief.", messages=[
    Message.user("Weather in Paris?"),
    Message(role="assistant", content=[ToolUseBlock(id="OURS-1", provider_id="call_abc", name="get_weather", arguments={"city": "Paris"})]),
    Message(role="user", content=[TextBlock(text="In French, please."), ToolResultBlock(tool_use_id="OURS-1", content=[TextBlock(text="18 C")])]),
])
print(json.dumps(to_payload(request)["messages"], indent=1))
EOF
```

**Try:** a real recorded OpenAI reply parsed into our types, then every kind of provider failure turned into one of our six errors.

```bash
uv run python - <<'EOF'
import asyncio, json, httpx
from agentreins.adapters.models.openai_compat import OpenAIChatModel, from_completion
from agentreins.types.content import Message
from agentreins.types.errors import ModelError
from agentreins.types.model import ModelRequest

body = json.loads(json.loads(open("tests/recorded/openai/tool_call.json").read())["body"])
[call] = from_completion(body).message.content
print("ours:", call.id, "| OpenAI's:", call.provider_id, "| args:", call.arguments)

async def main():
    for status, text in [(429, "slow down"), (401, "bad key"), (400, "maximum context length exceeded"), (503, "down")]:
        reply = lambda r, s=status, t=text: httpx.Response(s, json={"error": {"message": t}}, headers={"retry-after": "3"})
        model = OpenAIChatModel(client=httpx.AsyncClient(transport=httpx.MockTransport(reply)))
        try:
            await model.get_response(ModelRequest(model="x", messages=[Message.user("hi")]))
        except ModelError as e:
            print(status, "->", type(e).__name__, "| retryable:", e.retryable)
asyncio.run(main())
EOF
```

## 6. Runtime and `Agent`: a whole run

**Read:** [05-runtime.md](05-runtime.md), then [agent.py](../../src/agentreins/agent.py) and [loop.py](../../src/agentreins/runtime/loop.py) from `_Run.execute` (the loop in about 20 lines), then `model_turn` and `tool_turn`.

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

## 7. Structured output

**Read:** the "Structured output" section of [05-runtime.md](05-runtime.md), then [output.py](../../src/agentreins/runtime/output.py) and `output_turn` in [loop.py](../../src/agentreins/runtime/loop.py).

**Try:** the example. The scripted model first gives an invalid answer (`quantity=-9`), gets the validation error back, and corrects it.

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

## 8. Live (optional): a real model

Needs `OPENAI_API_KEY`; in this repo it is in the git-ignored `.env`. Each run costs well under $0.01.

```bash
set -a; . ./.env; set +a
uv run python examples/01_hello_tool_live.py     # the model calls the tool, in parallel for W1 and W2
uv run pytest -m live -v                         # all live tests, including structured output
```

## Where to go from here

- Each area page ends with **Extending it**: how to write your own store, redactor, tool source, policy or model adapter.
- The tests are the most precise description of behaviour: [tests/unit/runtime/test_loop.py](../../tests/unit/runtime/test_loop.py) lists everything a run can do, [tests/contract/](../../tests/contract/) the rules every adapter must follow.
