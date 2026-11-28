"""The public Agent: model resolution, defaults, run, run_sync, close."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agentreins import Agent, Budget, Principal, RunError, tool
from agentreins.adapters.event_stores.in_memory import InMemoryEventStore
from agentreins.adapters.event_stores.sqlite import SQLiteEventStore
from agentreins.adapters.models.openai_compat import OpenAIChatModel
from agentreins.testing import FakeModel
from agentreins.types.events import Event, RunStarted
from agentreins.types.model import ModelStreamEvent
from agentreins.types.tools import Effect, ToolCall, ToolContext, ToolResult, ToolSpec


@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Units on hand."""
    return 7


@tool
def create_po(sku: str) -> str:
    """Create a purchase order."""
    return "PO-1"


class RemoteSource:
    """A non-Python tool source (stands in for MCP)."""

    closed = False

    async def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="get_price",
                description="Price of a SKU.",
                input_schema={"type": "object", "properties": {"sku": {"type": "string"}}},
                effect=Effect.READ_ONLY,
            )
        ]

    async def call(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return ToolResult.text("12.50")

    async def close(self) -> None:
        self.closed = True


def script(*items: Any) -> FakeModel:
    return FakeModel(list(items))


# --- choosing the model ----------------------------------------------------------------


def test_model_string_builds_the_openai_adapter() -> None:
    agent = Agent("openai:gpt-4.1-mini")
    assert isinstance(agent._model, OpenAIChatModel)  # pyright: ignore[reportPrivateUsage]
    assert agent.model_name == "gpt-4.1-mini"


@pytest.mark.parametrize(
    ("model", "kwargs", "error"),
    [
        ("gpt-4.1-mini", {}, "provider:model-name"),
        ("openai:", {}, "provider:model-name"),
        ("anthropic:claude", {}, "unknown provider 'anthropic'"),
        ("openai:gpt-4.1-mini", {"model_name": "x"}, "only for adapter objects"),
        (OpenAIChatModel(api_key="k"), {}, "pass model_name="),
    ],
)
def test_bad_model_choices_explain_themselves(
    model: Any, kwargs: dict[str, Any], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        Agent(model, **kwargs)


def test_adapter_object_with_model_name() -> None:
    agent = Agent(OpenAIChatModel(base_url="http://localhost:11434/v1"), model_name="llama3")
    assert agent.model_name == "llama3"
    assert Agent(script()).model_name == "fake"


def test_cost_budget_is_refused_early() -> None:
    with pytest.raises(ValueError, match="max_cost_usd"):
        Agent(script(), budget=Budget(max_cost_usd=5))


# --- running -------------------------------------------------------------------------


async def test_run_with_function_tools_and_a_tool_source() -> None:
    remote = RemoteSource()
    model = script(
        FakeModel.call("get_stock", {"sku": "W1"}),
        FakeModel.call("get_price", {"sku": "W1"}),
        FakeModel.reply("7 units at 12.50."),
    )
    store = InMemoryEventStore()
    async with Agent(
        model, instructions="Be brief.", tools=[get_stock, remote], store=store, max_tokens=99
    ) as agent:
        result = await agent.run("Stock and price of W1?", principal=Principal(id="ana"))
    assert result.output == "7 units at 12.50."
    assert result.steps == 3
    assert model.requests[0].max_tokens == 99
    assert model.requests[0].system == "Be brief."
    assert {t.name for t in model.requests[0].tools} == {"get_stock", "get_price"}
    started = (await store.read(result.run_id))[0]
    assert isinstance(started, RunStarted)
    assert started.principal.id == "ana"
    assert remote.closed  # tool sources are closed with the agent


async def test_default_policy_stops_side_effects() -> None:
    agent = Agent(
        script(FakeModel.call("create_po", {"sku": "W1"})),
        tools=[create_po],
        store=InMemoryEventStore(),
    )
    with pytest.raises(RunError, match="approval required"):
        await agent.run("Order W1")


async def test_default_store_is_sqlite_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    agent = Agent(script(FakeModel.reply("hi")))
    assert not (tmp_path / "agentreins.db").exists()  # created on first run, not before
    result = await agent.run("hello")
    await agent.close()
    store = SQLiteEventStore(tmp_path / "agentreins.db")
    assert [e.type for e in await store.read(result.run_id)][-1] == "run.completed"
    await store.close()


async def test_one_agent_many_concurrent_runs() -> None:
    model = script(FakeModel.reply("a"), FakeModel.reply("b"), FakeModel.reply("c"))
    agent = Agent(model, store=InMemoryEventStore())
    results = await asyncio.gather(*[agent.run(f"q{i}") for i in range(3)])
    assert sorted(r.output for r in results) == ["a", "b", "c"]
    assert len({r.run_id for r in results}) == 3


async def test_hooks_are_wired() -> None:
    seen: list[str] = []

    class Hook:
        async def on_event(self, event: Event | ModelStreamEvent) -> None:
            seen.append(event.type)

    agent = Agent(script(FakeModel.reply("hello")), hooks=[Hook()], store=InMemoryEventStore())
    await agent.run("hi")
    assert seen[0] == "run.started"
    assert "text_delta" in seen
    assert seen[-1] == "run.completed"


# --- run_sync and close ------------------------------------------------------------


def test_run_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = Agent(script(FakeModel.reply("sync works"))).run_sync("hi")
    assert result.output == "sync works"


async def test_run_sync_refuses_inside_async_code() -> None:
    with pytest.raises(RuntimeError, match=r"await agent\.run"):
        Agent(script()).run_sync("hi")


async def test_close_leaves_objects_you_passed_in_open(tmp_path: Path) -> None:
    mine = SQLiteEventStore(tmp_path / "mine.db")
    agent = Agent(script(FakeModel.reply("x")), store=mine)
    await agent.run("hi")
    await agent.close()
    await agent.close()  # twice is fine
    assert await mine.list_unfinished() == []  # still usable: not closed by the agent
    await mine.close()
