"""SceneDeparture — the one path a scene takes out of a frame.

An empty push, a re-push under a new frame, a Hub's manifest (or death) and a
closed tab each take a scene out; :class:`SceneEviction` settles the frame left.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.replica.purge_sweep import PurgeSweep
from punt_lux.display.replica.scene_eviction import SceneEviction

if TYPE_CHECKING:
    from punt_lux.display.replica.frame import Frame
    from punt_lux.display.replica.frame_book import FrameBook
    from punt_lux.display.replica.frame_disposer import FrameDisposer
    from punt_lux.display.replica.owner_facts_cache import OwnerFactsStore
    from punt_lux.domain.identity import HubScopedKey
    from punt_lux.protocol import SceneMessage

__all__ = ["SceneDeparture"]


@final
class SceneDeparture:
    """Drops scenes from the frames holding them, in their own Hub's scope."""

    _book: FrameBook
    _eviction: SceneEviction
    _sweep: PurgeSweep
    __slots__ = ("_book", "_eviction", "_sweep")

    def __new__(
        cls, book: FrameBook, owner_facts: OwnerFactsStore, disposer: FrameDisposer
    ) -> Self:
        self = super().__new__(cls)
        self._book = book
        self._eviction = SceneEviction(book, owner_facts, disposer)
        self._sweep = PurgeSweep(book, self)
        return self

    def of_empty_push(self, key: HubScopedKey, msg: SceneMessage) -> None:
        """Drop the scene an empty push named; its frame takes the push's facts."""
        self._eviction.from_holder(key, msg.frame_owner_facts)

    def from_other_frame(self, frame: Frame, key: HubScopedKey) -> None:
        """Take ``key`` out of any frame but ``frame`` that owns it."""
        old_frame = self._book.frame_of_hub_scene(key)
        if old_frame is not None and old_frame is not frame:
            self._eviction.from_frame(old_frame, key.local, None)

    def of_dismissal(self, frame: Frame, scene_id: str) -> None:
        """Drop a scene with no word from the Hub: a closed tab, or a purged orphan."""
        self._eviction.from_frame(frame, scene_id, None)

    @property
    def sweep(self) -> PurgeSweep:
        """The sweep that drops every scene a Hub's manifest or death orphans."""
        return self._sweep
