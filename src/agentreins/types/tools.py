"""Tool types (ADR-0003).

TODO(M1): define Effect (read_only / idempotent / side_effecting) and the fields.
"""

from pydantic import BaseModel


class ToolSpec(BaseModel):
    """name, description, input_schema, effect, timeout. Placeholder."""


class ToolCall(BaseModel):
    """A model's request to call a tool: id, name, arguments. Placeholder."""


class ToolResult(BaseModel):
    """The outcome of a tool call: content, is_error. Placeholder."""


class ToolContext(BaseModel):
    """principal, credentials, run_id, cancellation, idempotency_key. Placeholder."""
