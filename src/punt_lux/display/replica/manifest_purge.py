"""ManifestPurge -- the manifest-purge policy DES-068's Hub reconciliation
drives, composed out of a :class:`FrameBook` (PY-OO-5, PY-IC-6): two
independent rules, never conflated into one condition. A sending Hub's
manifest disowns whatever it omits from *its own* scenes only; a scene whose
owning Hub is no longer live is swept unconditionally, regardless of any
manifest's content, so an unrelated live Hub's coincidentally-matching local
id can never shield an orphan.
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
    """Computes purge candidates against a composed :class:`FrameBook`'s
    own-Hub-scoped scene placement."""

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
        """``hub``'s own scenes its manifest omits -- scoped to ``hub``'s own
        entries by construction, so a second Hub's scenes are never
        candidates."""
        return [
            (HubScopedKey(hub, frame_id), scene_id)
            for scene_id, frame_id in self._book.scene_to_frame_for_hub(hub)
            if scene_id not in manifest
        ]

    def _orphans(self, live_hubs: frozenset[HubId]) -> list[tuple[HubScopedKey, str]]:
        """Every scene owned by a Hub no longer live -- independent of any
        manifest, so a dead Hub's scene is never shielded by an unrelated
        live Hub's coincidentally-matching manifest entry."""
        return [
            (HubScopedKey(dead_hub, frame_id), scene_id)
            for dead_hub in self._book.scene_hubs() - live_hubs
            for scene_id, frame_id in self._book.scene_to_frame_for_hub(dead_hub)
        ]
