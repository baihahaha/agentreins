"""Policy types (ADR-0004).

TODO(M1): define fields; Deny and RequireApproval carry a reason.
"""

from typing import TypeAlias

from pydantic import BaseModel


class PolicyRequest(BaseModel):
    """principal, tool spec, validated arguments, run/session IDs, budget used. Placeholder."""


class Allow(BaseModel):
    """The tool call may run. Placeholder."""


class Deny(BaseModel):
    """The tool call is refused; the model is told why. Placeholder."""


class RequireApproval(BaseModel):
    """The run pauses until a human approves or rejects. Placeholder."""


PolicyDecision: TypeAlias = Allow | Deny | RequireApproval
