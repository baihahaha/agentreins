"""Credentials from environment variables. Same key for every principal: development only.

Implements a port; may import only agentreins.types and agentreins.ports.
"""

import os
import re
from collections.abc import Mapping

from agentreins.types.errors import CredentialsUnavailable
from agentreins.types.identity import Credentials, Principal


class EnvCredentialProvider:
    """``get(principal, "erp")`` reads ``AGENTREINS_CRED_ERP``.

    Every principal gets the **same** secret, so the agent can do anything the key can.
    Fine for development; production needs a per-principal provider (ADR-0008), such as
    AWS STS role assumption or OAuth token exchange.
    """

    def __init__(
        self, prefix: str = "AGENTREINS_CRED_", environ: Mapping[str, str] | None = None
    ) -> None:
        self._prefix = prefix
        self._environ = environ

    async def get(self, principal: Principal, name: str) -> Credentials:
        variable = self.variable_for(name)
        environ = os.environ if self._environ is None else self._environ
        value = environ.get(variable)
        if not value:
            raise CredentialsUnavailable(f"environment variable {variable} is not set")
        return Credentials(name, value)

    def variable_for(self, name: str) -> str:
        """The environment variable read for a need, e.g. ``"erp-eu"`` -> ``..._ERP_EU``."""
        return self._prefix + re.sub(r"[^A-Za-z0-9]", "_", name).upper()
