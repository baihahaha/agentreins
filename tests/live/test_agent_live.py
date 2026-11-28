"""A whole agent run against the real OpenAI API. Run with ``pytest -m live``."""

import pytest
from pydantic import BaseModel, Field

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


class Order(BaseModel):
    sku: str
    quantity: int = Field(gt=0)


async def test_structured_output_with_a_real_model(openai_api_key: str) -> None:
    async with Agent(
        "openai:gpt-4.1-mini",
        output_type=Order,
        instructions="You are a stock clerk.",
        tools=[get_stock],
        store=InMemoryEventStore(),
        temperature=0,
    ) as agent:
        result = await agent.run("Order 2 more W1 than we have in stock.")
    order: Order = result.output
    assert order == Order(sku="W1", quantity=9)
