"""Model request/response types (ADR-0002 D4, D7, D8).

TODO(maintainer): define fields as listed in ADR-0002.
"""

from pydantic import BaseModel


class ModelRequest(BaseModel):
    """messages, system, tools, tool_choice, settings, provider_options. Placeholder."""


class ModelResponse(BaseModel):
    """message, stop_reason, usage, model, request_id. Placeholder."""


class ModelStreamEvent(BaseModel):
    """TextDelta / ToolUseStart / ToolArgsDelta / ReasoningDelta / UsageUpdate /
    final ModelResponse. Placeholder: likely becomes a union of event classes."""


class ModelCapabilities(BaseModel):
    """images, parallel tool calls, native structured output, max context. Placeholder."""
