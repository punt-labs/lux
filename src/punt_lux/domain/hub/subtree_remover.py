"""SubtreeRemover — tear a scene-root and its descendants out of Hub storage.

Removal touches four storage collaborators — the element index, the owner
tracker, the root registry, and the child index — and must drop every one for
a subtree in a single install-order walk, or a later ``resolve`` finds an
orphaned descendant the observer cascade already tore down. This class owns
that walk so ``HubDisplay`` stays a facade over the collaborators rather than
carrying the teardown mechanics itself.

Two entry points, one shared walk:

- ``remove_subtree`` — storage-only. The ``update`` remove tool and the
  ABC observer cascade both land here through ``HubDisplay.apply``.
- ``drop_root`` — one scene-root, owned or not (see its own docstring).
"""

from __future__ import annotations

import logging
from collections import deque
from itertools import repeat
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

        Walks the ``ChildIndex`` in install order and drops each descendant,
        then the element itself, so a later ``resolve`` fails loud rather
        than finding an orphan.
        """
        for descendant_id in self._children.descendants(scene_id, element_id):
            self._drop_storage(scene_id, descendant_id)
        self._drop_storage(scene_id, element_id)

    def drop_root(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        # Attribution for the failure log only.
        connection_id: ConnectionId | None = None,
    ) -> None:
        """Tear down one scene-root; logs and swallows per-root failures.

        An owned root flips ``mark_removed``; an unowned one is torn down
        directly -- its observer cascade would have no owner to route to.
        """
        try:
            root = self._roots.get(scene_id, element_id)
            is_owned = self._owners.get(scene_id, element_id) is not None
            (
                root.mark_removed()
                if root is not None and is_owned
                else self.remove_subtree(scene_id, element_id)
            )
        except Exception:  # noqa: BLE001 — fan-out cleanup boundary; continue past failure
            _log.exception(
                "drop_root: cleanup failed for root %s in scene %s (conn %s)",
                element_id,
                scene_id,
                connection_id,
            )

    def drop_scene_roots(self, scene_id: SceneId) -> None:
        """Tear down every root of a scene; snapshotted since drop_root mutates it."""
        element_ids = [
            element_id for element_id, _ in self._index.scene_root_items(scene_id)
        ]
        # Attribution for drop_root's failure log only.
        owned_by = self._owners.get
        owners = (
            owner.connection_id if (owner := owned_by(scene_id, eid)) else None
            for eid in element_ids
        )
        deque(map(self.drop_root, repeat(scene_id), element_ids, owners), maxlen=0)

    def _drop_storage(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop one element from every storage collaborator. Idempotent."""
        self._index.discard(scene_id, element_id)
        self._owners.discard(scene_id, element_id)
        self._roots.discard(scene_id, element_id)
        self._children.discard(scene_id, element_id)
