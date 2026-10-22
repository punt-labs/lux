"""PurgeSweep — drops every scene a Hub's manifest or death orphans.

The policy for which scenes are orphans is :class:`ManifestPurge`'s; the sweep
hands each one to the departure, so a purged scene leaves its frame the way every
other departing scene does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.replica.manifest_purge import ManifestPurge

if TYPE_CHECKING:
    from punt_lux.display.replica.frame_book import FrameBook
    from punt_lux.display.replica.scene_departure import SceneDeparture
    from punt_lux.domain.identity import HubId

__all__ = ["PurgeSweep"]


@final
class PurgeSweep:
    """Sweeps a manifest's orphans out of the frames that still hold them."""

    _book: FrameBook
    _purge: ManifestPurge
    _departure: SceneDeparture
    __slots__ = ("_book", "_departure", "_purge")

    def __new__(cls, book: FrameBook, departure: SceneDeparture) -> Self:
        self = super().__new__(cls)
        self._book = book
        self._purge = ManifestPurge(book)
        self._departure = departure
        return self

    def run(
        self, hub: HubId, manifest: frozenset[str], live_hubs: frozenset[HubId]
    ) -> None:
        """Drop each orphan scene whose frame is still held."""
        for frame_key, scene_id in self._purge.candidates(hub, manifest, live_hubs):
            frame = self._book.frame(frame_key.local, frame_key.hub)
            if frame is not None:
                self._departure.of_dismissal(frame, scene_id)
