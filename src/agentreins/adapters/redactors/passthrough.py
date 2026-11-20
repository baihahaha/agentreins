"""Pass-through redactor: changes nothing.

Implements a port; may import only agentreins.types and agentreins.ports.
"""

from agentreins.types.events import Event


class PassThroughRedactor:
    """Stores every event as-is. The default until the secrets redactor (M7)."""

    async def redact(self, event: Event) -> Event:
        return event
