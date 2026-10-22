"""SceneEviction — takes one scene out of its frame and settles what is left.

A frame the eviction empties is disposed, husk and all. One that stays occupied
keeps its owner snapshot unless the removed scene was its oldest, the one those
rows describe; then it takes the Hub's word. The owner *connection* departing is
different: its scenes stand, and the Hub's ``None`` leaves the snapshot in place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.identity import HubScopedKey

if TYPE_CHECKING:
    from punt_lux.display.replica.frame import Frame
    from punt_lux.display.replica.frame_book import FrameBook
    from punt_lux.display.replica.frame_disposer import FrameDisposer
    from punt_lux.display.replica.owner_facts_cache import OwnerFactsStore

__all__ = ["SceneEviction"]


@final
class SceneEviction:
    """Removes scenes from frames, keeping each frame's owner facts true."""

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

    def from_holder(
        self, key: HubScopedKey, facts_after: tuple[tuple[str, str], ...] | None
    ) -> None:
        """Remove ``key`` from whichever frame holds it; a no-op if none does."""
        holder = self._book.frame_of_hub_scene(key)
        if holder is not None:
            self.from_frame(holder, key.local, facts_after)

    def from_frame(
        self,
        frame: Frame,
        scene_id: str,
        facts_after: tuple[tuple[str, str], ...] | None,
    ) -> None:
        """Remove ``scene_id`` from ``frame``; dispose it if emptied, else re-own it."""
        was_oldest = frame.scene_order[:1] == [scene_id]
        if self._disposer.dismiss_framed_scene(frame, scene_id):
            self._disposer.dispose_frame(frame.frame_id, frame.hub)
            return
        frame_key = HubScopedKey(frame.hub, frame.frame_id)
        carried = facts_after if was_oldest else self._owner_facts.rows_for(frame_key)
        self._owner_facts.prune(frame_key)
        self._owner_facts.adopt(frame_key, carried)
