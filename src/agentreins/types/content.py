"""Content model: messages made of content blocks (ADR-0002 D3, ADR-0001 part 1)."""

from typing import Annotated, Literal, Self, TypeAlias

from pydantic import Field, JsonValue, model_validator

from agentreins.types._base import FrozenModel

Role: TypeAlias = Literal["user", "assistant"]


class TextBlock(FrozenModel):
    """Plain text."""

    type: Literal["text"] = "text"
    text: str


class ImageBlock(FrozenModel):
    """An image, given either inline (base64 ``data``) or by ``url``. Exactly one is set."""

    type: Literal["image"] = "image"
    media_type: str
    data: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.data is None) == (self.url is None):
            raise ValueError("ImageBlock needs exactly one of 'data' or 'url'")
        return self


class ToolUseBlock(FrozenModel):
    """The model asks to call a tool. A *request*, never an executed action.

    ``id`` is agentreins' own call ID, stable across providers and resumes (ADR-0001).
    ``provider_id`` is the ID the provider gave the call, kept for translation back.
    If the provider sent arguments that are not valid JSON, ``arguments`` is empty,
    ``raw_arguments`` holds the original text and ``parse_error`` says what was wrong;
    the tool harness turns that into an error result for the model.
    """

    type: Literal["tool_use"] = "tool_use"
    id: str
    provider_id: str | None = None
    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    raw_arguments: str | None = None
    parse_error: str | None = None

    @model_validator(mode="after")
    def _parse_error_keeps_raw(self) -> Self:
        if self.parse_error is not None and self.raw_arguments is None:
            raise ValueError("a ToolUseBlock with parse_error must keep raw_arguments")
        return self


ResultContent: TypeAlias = Annotated[TextBlock | ImageBlock, Field(discriminator="type")]


class ToolResultBlock(FrozenModel):
    """The outcome of a tool call, sent back to the model. ``tool_use_id`` is our call ID."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: list[ResultContent]
    is_error: bool = False


class ReasoningBlock(FrozenModel):
    """The model's reasoning. ``provider_signature`` is opaque and round-tripped as-is."""

    type: Literal["reasoning"] = "reasoning"
    text: str
    provider_signature: str | None = None


ContentBlock: TypeAlias = Annotated[
    TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock | ReasoningBlock,
    Field(discriminator="type"),
]

_ALLOWED: dict[str, frozenset[str]] = {
    "user": frozenset({"text", "image", "tool_result"}),
    "assistant": frozenset({"text", "image", "tool_use", "reasoning"}),
}


class Message(FrozenModel):
    """One conversation message: a role and a list of content blocks.

    Tool results travel in ``user`` messages; tool calls and reasoning only come from
    the ``assistant``. The system prompt is not a message (see ModelRequest.system).
    """

    role: Role
    content: list[ContentBlock]

    @model_validator(mode="after")
    def _blocks_match_role(self) -> Self:
        allowed = _ALLOWED[self.role]
        for block in self.content:
            if block.type not in allowed:
                raise ValueError(f"a {self.role} message cannot contain a {block.type} block")
        return self

    @classmethod
    def user(cls, text: str) -> "Message":
        """A user message with a single text block."""
        return cls(role="user", content=[TextBlock(text=text)])

    @classmethod
    def assistant(cls, text: str) -> "Message":
        """An assistant message with a single text block."""
        return cls(role="assistant", content=[TextBlock(text=text)])

    @property
    def text(self) -> str:
        """All text blocks joined together (empty if there are none)."""
        return "".join(block.text for block in self.content if isinstance(block, TextBlock))
