"""Event model: the envelope and every event type (ADR-0001, ADR-0005).

Events are immutable facts about a run, named in the past tense. The log of events is
the single source of truth; message history is a projection of it (built in M2).

Shape: flat, like Anthropic's API events. The envelope fields and the type-specific
fields sit side by side; a field is nested only when it is an object of its own
(``message``, ``usage``, ``result``).
"""

from datetime import UTC, datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import AwareDatetime, Field, JsonValue

from agentreins.types._base import FrozenModel
from agentreins.types.budget import Budget, Usage
from agentreins.types.content import Message
from agentreins.types.identity import Principal
from agentreins.types.ids import new_id
from agentreins.types.model import ModelResponse
from agentreins.types.tools import Effect, ToolResult, ToolSpec


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _EventBase(FrozenModel):
    """The envelope every event carries (ADR-0001 Part 2)."""

    event_id: str = Field(default_factory=new_id)
    run_id: str
    seq: int = Field(ge=0)
    """0, 1, 2… per run, no gaps. Defines order; the store enforces it (ADR-0005 D2)."""
    schema_version: int = Field(default=1, ge=1)
    """Version of this event type's fields, for migrating stored events later."""
    timestamp: AwareDatetime = Field(default_factory=_utc_now)


# --- run lifecycle -------------------------------------------------------------------


class RunStarted(_EventBase):
    """Everything needed to rebuild the run's configuration on resume."""

    type: Literal["run.started"] = "run.started"
    input: list[Message]
    system: str | None = None
    model: str
    tools: list[ToolSpec] = Field(default_factory=list[ToolSpec])
    budget: Budget = Field(default_factory=Budget)
    principal: Principal
    """Full principal, so an audit can explain policy decisions (roles, attributes)."""
    session_id: str | None = None
    run_key: str | None = None
    """Caller-supplied key that makes starting this run idempotent (REQUIREMENTS D3)."""
    governance_lifted: bool = False
    """True when run under ``agentreins.testing.no_governance()`` (REQUIREMENTS D7)."""


class RunCompleted(_EventBase):
    type: Literal["run.completed"] = "run.completed"
    output: Message
    usage: Usage
    cost_usd: float | None = Field(default=None, ge=0)


RunFailureReason: TypeAlias = Literal["max_steps", "budget_exceeded", "error", "cancelled"]


class RunFailed(_EventBase):
    type: Literal["run.failed"] = "run.failed"
    reason: RunFailureReason
    message: str = ""
    usage: Usage = Field(default_factory=Usage)


# --- model calls ---------------------------------------------------------------------


class ModelRequested(_EventBase):
    """Records *that* the model was asked. The full input is not stored (ADR-0001 b)."""

    type: Literal["model.requested"] = "model.requested"
    step: int = Field(ge=1)
    message_count: int = Field(ge=0)
    input_fingerprint: str
    """Hash of the exact request, so non-deterministic projection is detectable."""


class ModelResponded(_EventBase):
    type: Literal["model.responded"] = "model.responded"
    step: int = Field(ge=1)
    response: ModelResponse
    latency_ms: float = Field(ge=0)


class ModelFailed(_EventBase):
    """One failed attempt. Retries by the runtime each get their own event (ADR-0002 D5)."""

    type: Literal["model.failed"] = "model.failed"
    step: int = Field(ge=1)
    attempt: int = Field(ge=1)
    error: str
    """Error class name, e.g. ``"RateLimited"``."""
    message: str = ""
    retryable: bool


# --- tool calls ----------------------------------------------------------------------


class ToolCallRequested(_EventBase):
    """One per ``ToolUseBlock`` in a model response."""

    type: Literal["tool.call.requested"] = "tool.call.requested"
    call_id: str
    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


ToolRejectionReason: TypeAlias = Literal[
    "unknown_tool", "invalid_arguments", "policy_denied", "credentials_unavailable"
]


class ToolCallRejected(_EventBase):
    """The harness refused the call; it was never executed."""

    type: Literal["tool.call.rejected"] = "tool.call.rejected"
    call_id: str
    reason: ToolRejectionReason
    message: str
    """What the model is told."""


class ToolCallStarted(_EventBase):
    """The intent record: written *before* the tool runs (ADR-0001 rules)."""

    type: Literal["tool.call.started"] = "tool.call.started"
    call_id: str
    effect: Effect
    idempotency_key: str


class ToolCallCompleted(_EventBase):
    """The tool returned. ``result.is_error`` may still be true (a handled error)."""

    type: Literal["tool.call.completed"] = "tool.call.completed"
    call_id: str
    result: ToolResult
    duration_ms: float = Field(ge=0)


class ToolCallFailed(_EventBase):
    """The tool raised or timed out."""

    type: Literal["tool.call.failed"] = "tool.call.failed"
    call_id: str
    error: str
    timed_out: bool = False
    duration_ms: float = Field(ge=0)


# --- union and lookup ----------------------------------------------------------------

Event: TypeAlias = Annotated[
    RunStarted
    | RunCompleted
    | RunFailed
    | ModelRequested
    | ModelResponded
    | ModelFailed
    | ToolCallRequested
    | ToolCallRejected
    | ToolCallStarted
    | ToolCallCompleted
    | ToolCallFailed,
    Field(discriminator="type"),
]
"""Any event. Parsing stored JSON through this union yields the exact class."""

RunStatus: TypeAlias = Literal["running", "completed", "failed"]


class RunRef(FrozenModel):
    """A pointer to a run, returned by ``EventStore.find_run`` / ``list_unfinished``."""

    run_id: str
    run_key: str | None = None
    session_id: str | None = None
    status: RunStatus
    last_seq: int = Field(ge=0)
