"""DetailsScene — one client's Details scene: its name, its frame, its contents.

Everything about how a client's connection state is shown, held together: the
scene id it is always shown in, the frame that scene is placed in, and the
element tree that reports the facts. The operation reads the Hub and installs
what this builds; deciding what the reader sees is this class's job. Defaulting
an undeclared identity's fields is a separate job, owned by
:class:`~punt_lux.operations.client_identity_facts.ClientIdentityFacts` (DES-065
OO paydown) -- this class only frames and titles what that class reports.

The scene id is per client and stable: two clients' details read side by side,
and asking twice repaints the frame instead of stacking. It never expires.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.operations.client_identity_facts import ClientIdentityFacts
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.protocol.compositions.client_details import ClientDetailsComposition

if TYPE_CHECKING:
    from punt_lux.operations.models.query_clients import HubClient

__all__ = ["DetailsScene"]

# The scene and frame one client's details are shown in, and the table inside.
_SCENE_PREFIX = "lux.client-details"


@final
class DetailsScene:
    """The Details scene for one client: how it is named, framed, and filled."""

    _client: HubClient
    _label: str
    __slots__ = ("_client", "_label")

    def __new__(cls, client: HubClient, label: str) -> Self:
        self = super().__new__(cls)
        self._client = client
        self._label = label
        return self

    @property
    def scene_id(self) -> str:
        """The scene this client's details are always shown in."""
        return f"{_SCENE_PREFIX}.{self._client.connection_id}"

    def submission(self) -> SceneSubmission:
        """Offer the table in its own frame, titled for the client it describes."""
        title = f"{self._label} — client details"
        facts = ClientIdentityFacts(self._client, self._label).build()
        return SceneSubmission.of(
            ClientDetailsComposition.build(facts, element_id=f"{_SCENE_PREFIX}.table"),
            self.scene_id,
            ScenePresentation(
                frame_id=self.scene_id,
                title=title,
                frame_title=title,
                frame_size=(560, 340),
            ),
            None,
        )
