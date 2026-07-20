"""ConnectionDropper — teardown of every root a departing connection owned.

When a connection drops, the Hub must forget it as a client and remove each
scene-root it installed. An ABC root removes through the Observer cascade — the
dropper flips it and the parent composite unwinds the subtree — while a wire-only
root has no observer, so the dropper hands it straight to the ``SubtreeRemover``.
A scene left with no roots then has its frame forgotten, and a scene another
connection still holds a root in keeps its frame.

The dropper is a mirror of ``SubtreeInstaller`` and ``SubtreeRemover``: it owns
the disconnect-teardown responsibility so the store facade only delegates to it.
Forgetting an emptied frame runs the same no-root-remaining check every teardown
uses, injected as a callback so the one criterion lives in one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.child_index import ChildIndex
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.subtree_remover import SubtreeRemover
    from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["ConnectionDropper"]


@final
class ConnectionDropper:
    """Tears down a departing connection's roots, then forgets emptied frames."""

    _clients: HubClientRegistry
    _owners: OwnerTracker
    _children: ChildIndex
    _remover: SubtreeRemover
    _forget_frame: Callable[[SceneId], None]
    __slots__ = ("_children", "_clients", "_forget_frame", "_owners", "_remover")

    def __new__(
        cls,
        clients: HubClientRegistry,
        owners: OwnerTracker,
        children: ChildIndex,
        remover: SubtreeRemover,
        forget_frame: Callable[[SceneId], None],
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._owners = owners
        self._children = children
        self._remover = remover
        self._forget_frame = forget_frame
        return self

    def drop(self, connection_id: ConnectionId) -> None:
        """Forget the client, tear down each root it owned, forget emptied frames.

        Does NOT walk subtrees itself — that bypasses the Observer cascade and
        leaves parent composites' children stale. ABC roots drop via the
        cascade; wire-dataclass roots drop through the ``SubtreeRemover``.
        """
        self._clients.discard(connection_id)
        owned = self._owners.keys_for(connection_id)
        self._drop_owned_roots(connection_id, owned)
        for scene_id in {scene for scene, _ in owned}:
            self._forget_frame(scene_id)

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
