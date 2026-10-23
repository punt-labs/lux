"""ClientFacts -- one session's facts, and the Hub host they are reported beside."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.operations.models.query_clients import HubClient

__all__ = ["ClientFacts"]


@final
@dataclass(frozen=True, slots=True)
class ClientFacts:
    """What Details reports of one client: its row, and which Hub holds it.

    The Hub's hostname is one fact about the Hub, not about each client, so it
    travels beside the client's row instead of inside it.
    """

    client: HubClient
    hub_host: str

    @property
    def connection_id(self) -> str:
        """The connection the facts describe."""
        return self.client.connection_id
