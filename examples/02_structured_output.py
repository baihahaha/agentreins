"""Structured output: the answer comes back as a validated pydantic object.

The model gives its final answer by calling a hidden `final_result` tool whose
arguments are the fields of `Order`. Invalid answers are sent back for another try.
Offline: the model is scripted, including one invalid answer it must correct.

    uv run python examples/02_structured_output.py
"""

from pydantic import BaseModel, Field

from agentreins import Agent, tool
from agentreins.testing import FakeModel


class Order(BaseModel):
    sku: str
    quantity: int = Field(gt=0)


@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Units on hand for a product SKU."""
    return {"W1": 7}.get(sku, 0)


model = FakeModel(
    [
        FakeModel.call("get_stock", {"sku": "W1"}),
        FakeModel.call("final_result", {"sku": "W1", "quantity": -9}),  # invalid: sent back
        FakeModel.call("final_result", {"sku": "W1", "quantity": 9}),  # corrected
    ]
)

agent = Agent(model, output_type=Order, tools=[get_stock])
result = agent.run_sync("Order 2 more W1 than we have in stock.")

order = result.output  # an Order, not text
print(repr(order))
print(f"quantity + 1 = {order.quantity + 1}  ({result.steps} model calls)")
