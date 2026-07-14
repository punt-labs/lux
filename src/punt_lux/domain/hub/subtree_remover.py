"""SubtreeRemover — tear a scene-root and its descendants out of Hub storage.

Removal touches four storage collaborators — the element index, the owner
tracker, the root registry, and the child index — and must drop every one for
a subtree in a single install-order walk, or a later ``resolve`` finds an
orphaned descendant the observer cascade already tore down. This class owns
that walk so ``HubDisplay`` stays a facade over the collaborators rather than
carrying the teardown mechanics itself.

Two entry points, one shared walk:

- ``remove_subtree`` — the storage-only path. The ``update`` remove tool and
  the ABC observer cascade both land here through ``HubDisplay.apply``.
- ``drop_root`` — the disconnect path for one scene-root. An ABC root is flipped
  ``mark_removed`` so its observer cascade drives removal; a wire-only root has
  no observer, so it is torn down directly through ``remove_subtree``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.child_index import ChildIndex
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.root_registry import RootRegistry
    from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["SubtreeRemover"]

_log = logging.getLogger(__name__)


@final
class SubtreeRemover:
    """Drop subtrees from the four Hub storage collaborators in one walk."""

    _index: ElementIndex
    _owners: OwnerTracker
    _roots: RootRegistry
    _children: ChildIndex
    __slots__ = ("_children", "_index", "_owners", "_roots")

    def __new__(
        cls,
        index: ElementIndex,
        owners: OwnerTracker,
        roots: RootRegistry,
        children: ChildIndex,
    ) -> Self:
        self = super().__new__(cls)
        self._index = index
        self._owners = owners
        self._roots = roots
        self._children = children
        return self

    def remove_subtree(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Clear the element and every descendant from storage.

        Walks the ``ChildIndex`` to enumerate descendants in install order,
        then drops each in turn. For ABC subtrees the Observer cascade has
        already pruned the parent composite's children tuple; for wire-only
        subtrees no cascade exists, so this walk is the sole removal path.
        Either way, storage cleanup runs here so future ``resolve`` calls fail
        loud.
        """
        for descendant_id in self._children.descendants(scene_id, element_id):
            self._drop_storage(scene_id, descendant_id)
        self._drop_storage(scene_id, element_id)

    def drop_root(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        connection_id: ConnectionId,
    ) -> None:
        """Tear down one scene-root; logs and swallows per-root failures.

        Per-root cleanup is best-effort: a failure on one root is logged and
        the caller continues so a single misbehaving subtree cannot strand the
        rest of a disconnecting connection's state.
        """
        try:
            root = self._roots.get(scene_id, element_id)
            if root is not None:
                root.mark_removed()
            else:
                self.remove_subtree(scene_id, element_id)
        except Exception:  # noqa: BLE001 — fan-out cleanup boundary; continue past failure
            _log.exception(
                "drop_root: cleanup failed for root %s in scene %s (conn %s)",
                element_id,
                scene_id,
                connection_id,
            )

    def _drop_storage(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop one element from every storage collaborator. Idempotent."""
        self._index.discard(scene_id, element_id)
        self._owners.discard(scene_id, element_id)
        self._roots.discard(scene_id, element_id)
        self._children.discard(scene_id, element_id)
