"""Knowledge types: retrieved documents and memories (ADR-0010, ADR-0011)."""

from datetime import UTC, datetime

from pydantic import Field, JsonValue

from agentreins.types._base import FrozenModel
from agentreins.types.ids import new_id


class Document(FrozenModel):
    """A search result from a Retriever."""

    id: str
    content: str
    score: float | None = None
    source: str | None = None
    """Where it came from (URL, file path, table…), so the agent can cite it."""
    metadata: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class MemoryItem(FrozenModel):
    """One long-term memory."""

    content: str
    id: str = Field(default_factory=new_id)
    metadata: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
