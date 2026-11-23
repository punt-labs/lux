"""Validate a Hub facts response without confusing a process with its dial."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.operations.models.display_info import DisplayInfo

if TYPE_CHECKING:
    import http.client


class HubDisplayFacts:
    """A matching process must also name the Hub connection that answered."""

    _response: http.client.HTTPResponse

    def __new__(cls, response: http.client.HTTPResponse) -> Self:
        self = super().__new__(cls)
        self._response = response
        return self

    def identity(self, pid: int) -> str | None:
        response = self._response
        if response.status in (503, 504):
            return None
        if response.status != 200:
            raise ConnectionError(f"Hub Display probe returned HTTP {response.status}")
        facts = DisplayInfo.model_validate_json(response.read(65536))
        if facts.pid != pid:
            return None
        if not facts.hub_connection_id:
            raise ConnectionError("Hub does not report its Display dial; restart Hub")
        return facts.hub_connection_id
