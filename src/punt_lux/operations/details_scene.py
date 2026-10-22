"""DetailsScene — one client's Details scene: its name, its frame, its contents.

Everything about how a client's connection state is shown, held together: the
scene id it is always shown in, the frame that scene is placed in, and the
element tree that reports the facts. The operation reads the Hub and installs
what this builds; deciding what the reader sees is this class's job. Defaulting
an undeclared identity's fields belongs to ``ClientIdentityFacts``; this class
only frames and titles what that reports.

The scene id is per client and stable: two clients' details read side by side,
and asking twice repaints the frame instead of stacking. It never expires.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.details_frame import DetailsFrame
from punt_lux.operations.client_identity_facts import ClientIdentityFacts
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.protocol.compositions.client_details import ClientDetailsComposition

if TYPE_CHECKING:
    from punt_lux.domain.hub.named_sessions import NamedSession
    from punt_lux.operations.models.query_clients import HubClient

__all__ = ["DetailsScene"]

_TABLE_ID = "lux.client-details.table"


@final
class DetailsScene:
    """The Details scene for one client: how it is named, framed, and filled."""

    _client: HubClient
    _named: NamedSession
    _frame: DetailsFrame
    __slots__ = ("_client", "_frame", "_named")

    def __new__(cls, client: HubClient, named: NamedSession) -> Self:
        self = super().__new__(cls)
        self._client = client
        self._named = named
        self._frame = DetailsFrame(client.connection_id)
        return self

    @property
    def scene_id(self) -> str:
        """The scene this client's details are always shown in."""
        return self._frame.raw_id

    def submission(self) -> SceneSubmission:
        """Offer the table in its own frame, titled with the program."""
        facts = ClientIdentityFacts(self._client, self._named.name).build()
        return SceneSubmission.of(
            ClientDetailsComposition.build(facts, element_id=_TABLE_ID),
            self.scene_id,
            self._frame.presentation(self._named.program),
            None,
        )
