"""Model request/response types (ADR-0002 D4, D7, D8)."""

from typing import Annotated, Literal, Self, TypeAlias

from pydantic import Field, JsonValue, model_validator

from agentreins.types._base import FrozenModel
from agentreins.types.budget import Usage
from agentreins.types.content import Message
from agentreins.types.tools import ToolSpec

StopReason: TypeAlias = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal"]


class ForceTool(FrozenModel):
    """``tool_choice`` value that forces the model to call one specific tool."""

    name: str


ToolChoice: TypeAlias = Literal["auto", "none", "required"] | ForceTool


class ModelRequest(FrozenModel):
    """Everything an adapter needs for one model call."""

    model: str
    messages: list[Message]
    system: str | None = None
    tools: list[ToolSpec] = Field(default_factory=list[ToolSpec])
    tool_choice: ToolChoice = "auto"
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0)
    stop: list[str] = Field(default_factory=list[str])
    provider_options: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    """Provider-specific settings, passed to the adapter untouched (ADR-0002 D4)."""


class ModelResponse(FrozenModel):
    """One complete model reply."""

    message: Message
    stop_reason: StopReason
    usage: Usage
    model: str
    """The model that actually answered (may differ from the requested alias)."""
    request_id: str | None = None

    @model_validator(mode="after")
    def _reply_is_assistant(self) -> Self:
        if self.message.role != "assistant":
            raise ValueError("a ModelResponse message must have role 'assistant'")
        return self


class ModelCapabilities(FrozenModel):
    """What an adapter supports; the core checks these before sending (ADR-0002 D8)."""

    max_context_tokens: int = Field(gt=0)
    images: bool = False
    parallel_tool_calls: bool = True
    native_structured_output: bool = False


# --- stream events (ADR-0002 D7) ---------------------------------------------------


class TextDelta(FrozenModel):
    """A fragment of the reply's text."""

    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolUseStart(FrozenModel):
    """The model started a tool call; its arguments follow as ToolArgsDelta events."""

    type: Literal["tool_use_start"] = "tool_use_start"
    id: str
    name: str


class ToolArgsDelta(FrozenModel):
    """A fragment of a tool call's arguments."""

    type: Literal["tool_args_delta"] = "tool_args_delta"
    id: str
    delta: str
    """A fragment of the arguments' JSON text."""


class ReasoningDelta(FrozenModel):
    """A fragment of the model's reasoning, if the provider exposes it."""

    type: Literal["reasoning_delta"] = "reasoning_delta"
    text: str


class UsageUpdate(FrozenModel):
    """Token usage so far, sent by providers that report it while streaming."""

    type: Literal["usage_update"] = "usage_update"
    usage: Usage


class ResponseComplete(FrozenModel):
    """Always the last stream event: the complete response."""

    type: Literal["response_complete"] = "response_complete"
    response: ModelResponse


ModelStreamEvent: TypeAlias = Annotated[
    TextDelta | ToolUseStart | ToolArgsDelta | ReasoningDelta | UsageUpdate | ResponseComplete,
    Field(discriminator="type"),
]
