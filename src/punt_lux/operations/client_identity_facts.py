"""ClientIdentityFacts — one client's identity, normalized for a reader.

Split out of ``details_scene`` (DES-065 OO paydown): defaulting an undeclared
identity's kind/name/repo/agent into the Details table's facts is a distinct
reason to change from how that table is framed and titled
(:class:`~punt_lux.operations.details_scene.DetailsScene`). Behavior stays
with the data it defaults (oo.md): this class alone knows what "no identity
declared" reads as.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol.compositions.client_details import ClientDetails

if TYPE_CHECKING:
    from punt_lux.operations.models.query_clients import HubClient

__all__ = ["ClientIdentityFacts"]

# What a client that declared no identity calls itself: registered, unnamed.
_UNDECLARED = "client"


@final
class ClientIdentityFacts:
    """Normalize one client's connection state into the Details table's facts."""

    _client: HubClient
    _label: str
    __slots__ = ("_client", "_label")

    def __new__(cls, client: HubClient, label: str) -> Self:
        self = super().__new__(cls)
        self._client = client
        self._label = label
        return self

    def build(self) -> ClientDetails:
        """Return the facts the scene reports, as the rendering side reads them.

        An unidentified session reports as exactly that, never left blank.
        ``owned_scenes`` already arrives stripped to local ids -- ``HubClient``
        is built by ``QueryOperations._client``, which strips the composed
        store key at the introspection boundary before this class ever sees
        it, so no second strip is needed here.
        """
        identity = self._client.identity
        return ClientDetails(
            label=self._label,
            connection_id=self._client.connection_id,
            kind=identity.kind if identity is not None else "unidentified",
            name=identity.name if identity is not None else _UNDECLARED,
            repo=identity.repo if identity is not None else None,
            agent=identity.agent if identity is not None else None,
            connected_seconds=self._client.connected_seconds,
            lease=self._client.lease,
            subscribed_topics=tuple(self._client.subscribed_topics),
            owned_scenes=tuple(self._client.owned_scenes),
        )
