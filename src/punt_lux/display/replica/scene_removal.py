"""SceneRemoval — takes scenes out of frames, disposing a frame the removal empties.

Two removals share the shape: an empty push names a scene to drop, and a scene
re-pushed under a new frame leaves the old one. Either may empty a frame, and an
emptied frame goes with it, husk and all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final

from punt_lux.domain.identity import HubScopedKey

if TYPE_CHECKING:
    from punt_lux.display.replica.frame import Frame
    from punt_lux.display.replica.frame_book import FrameBook
    from punt_lux.display.replica.owner_facts_cache import OwnerFactsStore
    from punt_lux.domain.identity import HubId

__all__ = ["FrameDisposer", "SceneRemoval"]


class FrameDisposer(Protocol):
    """What removal needs from the replica: dismiss one scene, dispose a frame."""

    def dismiss_framed_scene(self, frame: Frame, scene_id: str) -> bool:
        """Remove a scene from ``frame``; return True if the frame is now empty."""
        ...

    def dispose_frame(self, frame_id: str, hub: HubId) -> list[str]:
        """Throw a frame and its scenes out."""
        ...


@final
class SceneRemoval:
    """Drops scenes from the frames holding them, in their own Hub's scope."""

    _book: FrameBook
    _owner_facts: OwnerFactsStore
    _disposer: FrameDisposer
    __slots__ = ("_book", "_disposer", "_owner_facts")

    def __new__(
        cls, book: FrameBook, owner_facts: OwnerFactsStore, disposer: FrameDisposer
    ) -> Self:
        self = super().__new__(cls)
        self._book = book
        self._owner_facts = owner_facts
        self._disposer = disposer
        return self

    def of_empty_push(
        self, key: HubScopedKey, owner_facts: tuple[tuple[str, str], ...] | None
    ) -> None:
        """Drop the scene an empty push named, resolved by its own Hub only.

        The push still names the Hub's current canonical owner, who may differ
        from the one a surviving scene was adopted under, so a frame that is
        still held takes the facts; one that is already gone gets no entry.
        """
        stale = self._book.frame_of_hub_scene(key)
        if stale is not None:
            self._owner_facts.adopt(
                HubScopedKey(stale.hub, stale.frame_id), owner_facts
            )
            self._drop(stale, key)

    def from_other_frame(self, frame: Frame, key: HubScopedKey) -> None:
        """Take ``key`` out of any frame but ``frame`` that owns it."""
        old_frame = self._book.frame_of_hub_scene(key)
        if old_frame is not None and old_frame.frame_id != frame.frame_id:
            self._drop(old_frame, key)

    def _drop(self, frame: Frame, key: HubScopedKey) -> None:
        """Dismiss ``key`` from ``frame``, disposing the frame if now empty."""
        if self._disposer.dismiss_framed_scene(frame, key.local):
            self._disposer.dispose_frame(frame.frame_id, frame.hub)
