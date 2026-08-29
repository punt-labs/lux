"""Which element ids a change dropped, and who has to be told about it.

Split out of :class:`~punt_lux.display.replica.scene_replica.SceneReplica`,
whose own docstring names this as the cross-cutting concern it layers over the
frames. Collecting the ids in a tree, working out which of them no surviving
scene still holds, and calling the Hub back about the difference is one job with
one reason to change; owning the scene graph is another.

Staleness is a claim about *survival*, not about visibility. An id is stale when
no framed scene holds it any more, so a frame the user merely put away keeps
every one of its ids alive — which is why closing a frame drains this Display's
own queued interactions directly rather than through :meth:`StaleIds.notify`,
and why :meth:`StaleIds.of_frame` exists beside it (DES-065 R8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.replica.element_walk import SceneTreeWalk

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from punt_lux.display.replica.frame import Frame
    from punt_lux.display.replica.frame_book import FrameBook
    from punt_lux.protocol import SceneMessage

__all__ = ["OnSceneReplacedFn", "StaleIds"]

type OnSceneReplacedFn = Callable[[list[str]], None]


@final
class StaleIds:
    """Report the element ids a change retired, to whoever asked to be told."""

    _book: FrameBook
    _on_scene_replaced: OnSceneReplacedFn
    _walk: SceneTreeWalk
    __slots__ = ("_book", "_on_scene_replaced", "_walk")

    def __new__(cls, book: FrameBook, on_scene_replaced: OnSceneReplacedFn) -> Self:
        self = super().__new__(cls)
        self._book = book
        self._on_scene_replaced = on_scene_replaced
        self._walk = SceneTreeWalk()
        return self

    def in_tree(self, elements: Sequence[object]) -> set[str]:
        """Return every element id in ``elements``, recursing containers.

        An element with no id — a separator — contributes nothing. It cannot be
        addressed, so it can be neither stale to the Hub nor the target of a
        queued interaction, and carrying an empty string through either path
        only puts a name on the wire that names nothing.
        """
        ids: set[str] = set()
        for elem in elements:
            ids.update(self._walk.collect_ids(elem))
        ids.discard("")
        return ids

    def of_frame(self, frame: Frame) -> set[str]:
        """Return every element id held by every scene in ``frame``."""
        ids: set[str] = set()
        for scene in frame.scenes.values():
            ids |= self.in_tree(scene.elements)
        return ids

    def dropped_by(self, msg: SceneMessage, old_scene: SceneMessage) -> set[str]:
        """Return the ids ``msg`` no longer carries that ``old_scene`` did."""
        return self.in_tree(old_scene.elements) - self.in_tree(msg.elements)

    def notify(self, candidate_ids: set[str]) -> list[str]:
        """Report and return the candidates no surviving framed scene holds.

        Survivor-aware, so replacing one scene never reports an id another scene
        still shows: the ids are the whole workspace's, not one tree's.
        """
        stale = candidate_ids - self._surviving()
        if stale:
            self._on_scene_replaced(list(stale))
        return list(stale)

    def _surviving(self) -> set[str]:
        """Return every element id held by any framed scene still stored."""
        ids: set[str] = set()
        for scene in self._book.framed_scenes():
            ids |= self.in_tree(scene.elements)
        return ids
