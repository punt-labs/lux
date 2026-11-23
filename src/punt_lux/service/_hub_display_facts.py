"""Validate a Hub facts response without confusing a process with its dial."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.operations.models.display_info import DisplayInfo

if TYPE_CHECKING:
    import http.client


class HubDisplayFacts(DisplayInfo, frozen=True):
    """A matching process must also name the Hub connection that answered."""

    @classmethod
    def read(cls, response: http.client.HTTPResponse) -> Self:
        """Read validated facts from a successful Hub reply."""
        if response.status != 200:
            raise ConnectionError(f"Hub Display probe returned HTTP {response.status}")
        return cls.model_validate_json(response.read(65536))

    def identity(self, pid: int) -> str | None:
        if self.pid != pid:
            return None
        if not self.hub_connection_id.name:
            raise ConnectionError("Hub does not report its Display dial; restart Hub")
        return self.hub_connection_id.name
