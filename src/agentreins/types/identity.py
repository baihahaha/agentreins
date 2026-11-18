"""Identity types (REQUIREMENTS G1, ADR-0008)."""

from typing import NoReturn

from pydantic import Field

from agentreins.types._base import FrozenModel


class Principal(FrozenModel):
    """Who a run acts for. Verified by the host application, never by agentreins."""

    id: str
    tenant: str | None = None
    roles: list[str] = Field(default_factory=list[str])
    attributes: dict[str, str] = Field(default_factory=dict[str, str])


class Credentials:
    """Secret material for one principal and one need (e.g. ``"erp"``).

    Deliberately *not* a pydantic model: it cannot be printed, serialized, pickled or
    placed in a pydantic model, so it cannot reach the event log by accident
    (ADR-0008 D2). Read the secret only with :meth:`reveal`.
    """

    __slots__ = ("_secret", "name")

    def __init__(self, name: str, secret: str) -> None:
        self.name = name
        self._secret = secret

    def reveal(self) -> str:
        """Return the secret. Call only at the point of use, never to log or store it."""
        return self._secret

    def __repr__(self) -> str:
        return f"Credentials(name={self.name!r}, secret=***)"

    __str__ = __repr__

    def __reduce__(self) -> NoReturn:
        raise TypeError("Credentials cannot be pickled or copied")
