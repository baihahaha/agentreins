"""Identity types (REQUIREMENTS G1, ADR-0008).

TODO(maintainer): Credentials must refuse to be printed, serialized or stored (ADR-0008 D2).
"""

from pydantic import BaseModel


class Principal(BaseModel):
    """Who a run acts for: user ID, tenant, roles. Placeholder."""


class Credentials(BaseModel):
    """Secret material for one principal and one need (e.g. "erp"). Placeholder."""
