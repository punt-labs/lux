"""ConnectionDropper — teardown of every root a departing connection owned.

When a connection drops, the Hub must forget it as a client and remove each
scene-root it installed. An ABC root removes through the Observer cascade — the
dropper flips it and the parent composite unwinds the subtree — while a wire-only
root has no observer, so the dropper hands it straight to the ``SubtreeRemover``.

The dropper is a mirror of ``SubtreeInstaller`` and ``SubtreeRemover``: it owns
the disconnect-teardown responsibility so the store facade only delegates to it.
``drop`` returns every scene it touched so the caller can repaint them: a scene
the drop emptied is blanked on the next resend, and a scene another connection
still holds a root in is repainted with its remaining content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.child_index import ChildIndex
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.subtree_remover import SubtreeRemover
    from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["ConnectionDropper"]


@final
class ConnectionDropper:
    """Tears down a departing connection's roots and names the scenes it touched."""

    _clients: HubClientRegistry
    _owners: OwnerTracker
    _children: ChildIndex
    _remover: SubtreeRemover
    __slots__ = ("_children", "_clients", "_owners", "_remover")

    def __new__(
        cls,
        clients: HubClientRegistry,
        owners: OwnerTracker,
        children: ChildIndex,
        remover: SubtreeRemover,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._owners = owners
        self._children = children
        self._remover = remover
        return self

    def drop(self, connection_id: ConnectionId) -> frozenset[SceneId]:
        """Forget the client, tear down each root it owned; return touched scenes.

        Does NOT walk subtrees itself — that bypasses the Observer cascade and
        leaves parent composites' children stale. ABC roots drop via the
        cascade; wire-dataclass roots drop through the ``SubtreeRemover``. The
        returned scenes are marked dirty by the caller so the replicator blanks
        the ones the drop emptied and repaints the ones a survivor still holds.
        """
        self._clients.discard(connection_id)
        owned = self._owners.keys_for(connection_id)
        self._drop_owned_roots(connection_id, owned)
        return frozenset(scene for scene, _ in owned)

    def _drop_owned_roots(
        self,
        connection_id: ConnectionId,
        owned: tuple[tuple[SceneId, ElementId], ...],
    ) -> None:
        """Tear down each scene-root the connection owned, leaving children to
        the Observer cascade."""
        for scene_id, element_id in owned:
            if self._children.is_root(scene_id, element_id):
                self._remover.drop_root(scene_id, element_id, connection_id)
