"""Hello, tool, with a real model (OpenAI). Costs well under $0.01.

Needs OPENAI_API_KEY in the environment, and the providers extra (httpx):

    export OPENAI_API_KEY=sk-...        # or, in this repo: set -a; . ./.env; set +a
    uv run python examples/01_hello_tool_live.py
"""

from agentreins import Agent, tool


@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Units on hand for a product SKU."""
    return {"W1": 7, "W2": 3}.get(sku, 0)


agent = Agent(
    "openai:gpt-4.1-mini",
    instructions="You are a stock clerk. Use the tools; answer in one sentence.",
    tools=[get_stock],
)
result = agent.run_sync("How many W1 and W2 do we have?")

print(result.output)
print(
    f"{result.steps} model calls, {result.usage.input_tokens + result.usage.output_tokens} tokens"
)
