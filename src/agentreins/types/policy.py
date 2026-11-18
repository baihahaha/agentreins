"""Policy types (ADR-0004)."""

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, JsonValue

from agentreins.types._base import FrozenModel
from agentreins.types.budget import Usage
from agentreins.types.identity import Principal
from agentreins.types.tools import ToolSpec


class PolicyRequest(FrozenModel):
    """Everything a policy may base its decision on. Arguments are already validated."""

    principal: Principal
    tool: ToolSpec
    arguments: dict[str, JsonValue]
    run_id: str
    session_id: str | None = None
    usage: Usage = Field(default_factory=Usage)
    """Usage so far in the run, for budget-aware rules."""


class Allow(FrozenModel):
    """The tool call may run."""

    type: Literal["allow"] = "allow"


class Deny(FrozenModel):
    """The tool call is refused; the model is told ``reason``."""

    type: Literal["deny"] = "deny"
    reason: str


class RequireApproval(FrozenModel):
    """The run pauses until a human approves or rejects."""

    type: Literal["require_approval"] = "require_approval"
    reason: str


PolicyDecision: TypeAlias = Annotated[Allow | Deny | RequireApproval, Field(discriminator="type")]
