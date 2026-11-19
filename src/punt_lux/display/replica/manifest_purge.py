"""Select stale scenes for removal using the frame book and Hub manifests.

A sending Hub's manifest disowns whatever it omits from *its own* scenes only; a scene
whose owning Hub is no longer live is swept unconditionally, regardless of any
manifest's content, so an unrelated live Hub's coincidentally-matching local id can
never shield an orphan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.identity import HubScopedKey

if TYPE_CHECKING:
    from punt_lux.display.replica.frame_book import FrameBook
    from punt_lux.domain.identity import HubId

__all__ = ["ManifestPurge"]


@final
class ManifestPurge:
    """Compute purge candidates using Hub-scoped scene placement."""

    _book: FrameBook
    __slots__ = ("_book",)

    def __new__(cls, book: FrameBook) -> Self:
        self = super().__new__(cls)
        self._book = book
        return self

    def candidates(
        self, hub: HubId, manifest: frozenset[str], live_hubs: frozenset[HubId]
    ) -> list[tuple[HubScopedKey, str]]:
        """Every ``(frame_key, scene_id)`` pair to purge."""
        return self._own_hub(hub, manifest) + self._orphans(live_hubs)

    def _own_hub(
        self, hub: HubId, manifest: frozenset[str]
    ) -> list[tuple[HubScopedKey, str]]:
        """Find scenes this Hub owns but omitted from its manifest."""
        return [
            (HubScopedKey(hub, frame_id), scene_id)
            for scene_id, frame_id in self._book.scene_to_frame_for_hub(hub)
            if scene_id not in manifest
        ]

    def _orphans(self, live_hubs: frozenset[HubId]) -> list[tuple[HubScopedKey, str]]:
        """Find all scenes owned by Hubs that are no longer live."""
        return [
            (HubScopedKey(dead_hub, frame_id), scene_id)
            for dead_hub in self._book.scene_hubs() - live_hubs
            for scene_id, frame_id in self._book.scene_to_frame_for_hub(dead_hub)
        ]
