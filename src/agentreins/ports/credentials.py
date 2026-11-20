"""CredentialProvider port (ADR-0008)."""

from typing import Protocol

from agentreins.types.identity import Credentials, Principal


class CredentialProvider(Protocol):
    """Supplies credentials for one principal and one declared need (e.g. "erp").

    Called on every tool call; the provider owns caching and expiry (D3).
    """

    async def get(self, principal: Principal, name: str) -> Credentials:
        """Return the credential for need ``name``, scoped to ``principal``.

        Raise an error (e.g. ``CredentialsUnavailable``) if none can be supplied; never
        put the secret in the error message.
        """
        ...
