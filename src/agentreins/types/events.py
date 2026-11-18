"""Event model: the envelope and every event type (ADR-0001, ADR-0005).

TODO(M1): define the envelope (event_id, run_id, seq, type, schema_version,
timestamp, payload) and the event types.
"""

from pydantic import BaseModel


class Event(BaseModel):
    """One immutable fact in a run's log. Placeholder."""


class RunRef(BaseModel):
    """A pointer to a run: run_id, key, status. Placeholder."""
