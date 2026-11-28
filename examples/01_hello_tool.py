"""Hello, tool: an agent answers a question by calling a Python function.

Offline: the model is scripted with FakeModel, so this runs anywhere, for free.
For the same agent with a real model, see 01_hello_tool_live.py.

    uv run python examples/01_hello_tool.py
"""

from agentreins import Agent, tool
from agentreins.testing import FakeModel


@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Units on hand for a product SKU."""
    return {"W1": 7, "W2": 3}.get(sku, 0)


# What a real model would do: call the tool, then answer with its result.
model = FakeModel(
    [
        FakeModel.call("get_stock", {"sku": "W1"}),
        FakeModel.reply("We have 7 units of W1."),
    ]
)

agent = Agent(model, instructions="You are a stock clerk.", tools=[get_stock])
result = agent.run_sync("How many W1 do we have?")

print(result.output)
print(f"{result.steps} model calls; every step is saved in agentreins.db (run {result.run_id})")
