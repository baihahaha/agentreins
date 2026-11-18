"""Tool types (ADR-0003)."""

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import Field, JsonValue

from agentreins.types._base import FrozenModel
from agentreins.types.content import ResultContent, TextBlock
from agentreins.types.identity import Credentials, Principal


class Effect(StrEnum):
    """What a tool can do to the world. Drives the default policy (ADR-0004 D4)."""

    READ_ONLY = "read_only"
    IDEMPOTENT = "idempotent"
    SIDE_EFFECTING = "side_effecting"


class ToolSpec(FrozenModel):
    """Describes one tool: what the model sees, plus how agentreins governs it."""

    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str
    input_schema: dict[str, JsonValue]
    effect: Effect
    timeout_seconds: float = Field(default=30.0, gt=0)
    requires: list[str] = Field(default_factory=list[str])
    """Credential needs, e.g. ``["erp"]`` (ADR-0008 D1)."""


class ToolCall(FrozenModel):
    """A tool call as the harness receives it. ``id`` is agentreins' call ID."""

    id: str
    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class ToolResult(FrozenModel):
    """What a tool returns."""

    content: list[ResultContent]
    is_error: bool = False

    @classmethod
    def text(cls, text: str) -> "ToolResult":
        """A successful result with a single text block."""
        return cls(content=[TextBlock(text=text)])

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        """An error result the model will see, e.g. a validation or policy message."""
        return cls(content=[TextBlock(text=message)], is_error=True)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What a tool receives at runtime (ADR-0003 D3).

    A plain dataclass, not a pydantic model: it holds Credentials and a live
    cancellation signal, and is never serialized or stored.
    """

    principal: Principal
    run_id: str
    idempotency_key: str
    """Stable for this call across retries and resumes. Pass it to the real system."""
    credentials: dict[str, Credentials] = field(default_factory=dict[str, Credentials])
    """Credentials for each need declared in ``ToolSpec.requires``."""
    cancellation: asyncio.Event = field(default_factory=asyncio.Event)
    """Set when the run is being cancelled; long-running tools should check it."""
