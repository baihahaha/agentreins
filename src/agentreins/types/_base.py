"""Base class shared by all agentreins data types."""

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Immutable, strict-shape model.

    - ``frozen``: fields cannot be reassigned after creation. Note this is shallow:
      the *contents* of a list or dict field are not frozen. Treat them as read-only.
    - ``extra="forbid"``: unknown fields are rejected, so typos fail loudly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
