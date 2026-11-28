"""A whole agent run against the real OpenAI API. Run with ``pytest -m live``."""

import pytest

from agentreins import Agent, tool
from agentreins.adapters.event_stores.in_memory import InMemoryEventStore

pytestmark = pytest.mark.live


@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Units on hand for a product SKU."""
    return {"W1": 7, "W2": 3}.get(sku, 0)


async def test_agent_answers_from_its_tool(openai_api_key: str) -> None:
    store = InMemoryEventStore()
    async with Agent(
        "openai:gpt-4.1-mini",
        instructions="You are a stock clerk. Use the tools; answer in one sentence.",
        tools=[get_stock],
        store=store,
        temperature=0,
    ) as agent:
        result = await agent.run("How many W1 do we have?")
    assert "7" in result.output
    types = [e.type for e in await store.read(result.run_id)]
    assert "tool.call.completed" in types
    assert types[-1] == "run.completed"
