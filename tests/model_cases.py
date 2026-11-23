"""Requests shared by the live tests (real API) and the recorded tests (replayed)."""

import os

from agentreins.types.content import Message, TextBlock, ToolResultBlock, ToolUseBlock
from agentreins.types.model import ForceTool, ModelRequest, ModelResponse
from agentreins.types.tools import Effect, ToolSpec

LIVE_MODEL = os.environ.get("AGENTREINS_LIVE_MODEL", "gpt-4.1-mini")

WEATHER = ToolSpec(
    name="get_weather",
    description="Current weather for a city.",
    input_schema={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
        "additionalProperties": False,
    },
    effect=Effect.READ_ONLY,
)


def case(name: str, model: str = LIVE_MODEL) -> ModelRequest:
    """The request for one recorded/live case. ``stream_*`` cases reuse the plain one."""
    base = name.removeprefix("stream_")
    if base == "text":
        return ModelRequest(
            model=model,
            system="Answer in one short sentence.",
            messages=[Message.user("What is the capital of France?")],
            max_tokens=50,
            temperature=0,
        )
    if base == "tool_call":
        return ModelRequest(
            model=model,
            messages=[Message.user("What's the weather in Paris?")],
            tools=[WEATHER],
            tool_choice=ForceTool(name="get_weather"),
            max_tokens=50,
            temperature=0,
        )
    if base == "tool_result":
        return ModelRequest(
            model=model,
            messages=[
                Message.user("What's the weather in Paris?"),
                Message(
                    role="assistant",
                    content=[
                        ToolUseBlock(
                            id="call-1",
                            provider_id="call_paris1",
                            name="get_weather",
                            arguments={"city": "Paris"},
                        )
                    ],
                ),
                Message(
                    role="user",
                    content=[
                        ToolResultBlock(
                            tool_use_id="call-1", content=[TextBlock(text="18 degrees and sunny")]
                        )
                    ],
                ),
            ],
            tools=[WEATHER],
            max_tokens=60,
            temperature=0,
        )
    raise KeyError(name)


CASES = ["text", "tool_call", "tool_result", "stream_text", "stream_tool_call"]


def check(name: str, response: ModelResponse) -> None:
    """What a real model must have answered for each case (used live and on replay)."""
    base = name.removeprefix("stream_")
    assert response.message.role == "assistant"
    assert response.usage.input_tokens > 0
    if base == "text":
        assert "Paris" in response.message.text
        assert response.stop_reason == "end_turn"
    elif base == "tool_call":
        [call] = [b for b in response.message.content if isinstance(b, ToolUseBlock)]
        assert call.name == "get_weather"
        assert "paris" in str(call.arguments.get("city", "")).lower()
        assert call.provider_id
        assert response.stop_reason == "tool_use"
    elif base == "tool_result":
        assert "18" in response.message.text
