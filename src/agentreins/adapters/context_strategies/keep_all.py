"""Context strategy: keep everything.

Implements a port; may import only agentreins.types and agentreins.ports.
"""

from agentreins.types.content import Message


class KeepAll:
    """Sends the whole conversation every turn. The default until truncation (M8).

    If the conversation outgrows the model's window, the provider answers
    ``ContextTooLong`` and the run fails cleanly: nothing is silently dropped.
    """

    async def select(self, messages: list[Message], token_budget: int) -> list[Message]:
        return messages
