"""Fake model: scripted, deterministic, for tests and examples.

Implements a port; may import only agentreins.types and agentreins.ports.
"""

import json
from collections.abc import AsyncIterator, Callable, Iterable

from pydantic import JsonValue

from agentreins.types.budget import Usage
from agentreins.types.content import Message, ReasoningBlock, TextBlock, ToolUseBlock
from agentreins.types.ids import new_id
from agentreins.types.model import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ReasoningDelta,
    ResponseComplete,
    TextDelta,
    ToolArgsDelta,
    ToolUseStart,
    UsageUpdate,
)

ScriptItem = ModelResponse | BaseException | Callable[[ModelRequest], ModelResponse]
"""One scripted turn: a reply, an error to raise, or a function computing the reply."""


class FakeModel:
    """A model that replies from a script, one item per call, in order.

    Every request is recorded in :attr:`requests`, so tests can check what was sent.
    Streaming is derived from the same script, so ``get_response`` and
    ``stream_response`` always agree (ADR-0002 D1).

    >>> model = FakeModel([FakeModel.call("get_stock", {"sku": "W1"}), FakeModel.reply("7")])
    """

    def __init__(
        self,
        script: Iterable[ScriptItem] = (),
        *,
        capabilities: ModelCapabilities | None = None,
        chunk_size: int = 8,
    ) -> None:
        self._script = list(script)
        self._capabilities = capabilities or ModelCapabilities(
            max_context_tokens=128_000, images=True
        )
        self._chunk_size = chunk_size
        self.requests: list[ModelRequest] = []
        """Every request received, in order."""

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    async def get_response(self, request: ModelRequest) -> ModelResponse:
        return self._next(request)

    async def stream_response(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        response = self._next(request)
        for event in stream_events(response, self._chunk_size):
            yield event

    @property
    def remaining(self) -> int:
        """How many scripted items have not been used yet."""
        return len(self._script)

    # --- building script items --------------------------------------------------------

    @staticmethod
    def reply(text: str, *, usage: Usage | None = None) -> ModelResponse:
        """A plain text answer that ends the turn."""
        return ModelResponse(
            message=Message.assistant(text),
            stop_reason="end_turn",
            usage=usage or Usage(input_tokens=10, output_tokens=len(text.split())),
            model="fake",
        )

    @staticmethod
    def call(
        name: str, arguments: dict[str, JsonValue] | None = None, *, text: str = ""
    ) -> ModelResponse:
        """A reply that asks for one tool call (optionally with some text first)."""
        blocks: list[TextBlock | ToolUseBlock] = [TextBlock(text=text)] if text else []
        blocks.append(ToolUseBlock(id=new_id(), name=name, arguments=arguments or {}))
        return ModelResponse(
            message=Message(role="assistant", content=list(blocks)),
            stop_reason="tool_use",
            usage=Usage(input_tokens=10, output_tokens=5),
            model="fake",
        )

    # --- internals --------------------------------------------------------------------

    def _next(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._script:
            raise RuntimeError(
                f"FakeModel script is exhausted after {len(self.requests) - 1} calls"
            )
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ModelResponse):
            return item
        return item(request)


def stream_events(response: ModelResponse, chunk_size: int = 8) -> list[ModelStreamEvent]:
    """The stream events a provider would send for ``response``, ending with it.

    Text and tool arguments are cut into pieces of ``chunk_size`` characters, the way
    real providers deliver them.
    """
    events: list[ModelStreamEvent] = []
    for block in response.message.content:
        if isinstance(block, ReasoningBlock):
            events += [ReasoningDelta(text=p) for p in _pieces(block.text, chunk_size)]
        elif isinstance(block, TextBlock):
            events += [TextDelta(text=p) for p in _pieces(block.text, chunk_size)]
        elif isinstance(block, ToolUseBlock):
            events.append(ToolUseStart(id=block.id, name=block.name))
            raw = block.raw_arguments or json.dumps(block.arguments)
            events += [ToolArgsDelta(id=block.id, delta=p) for p in _pieces(raw, chunk_size)]
    events.append(UsageUpdate(usage=response.usage))
    events.append(ResponseComplete(response=response))
    return events


def _pieces(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]
