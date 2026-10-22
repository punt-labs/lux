"""SceneListing — build the scene/frame summaries ``list_scenes`` reports.

Split out of ``queries`` (DES-065 OO paydown): grouping scenes by frame, and
reading each scene's owners and quarantine status, is one cohesive concern,
distinct from listing the Hub's connected clients
(:class:`~punt_lux.operations.client_listing.ClientListing`) or walking one
scene's element tree (``QueryOperations._inspect``) -- three different
reasons to change that ``queries.py`` used to bundle into one class. This is
part of the reach-around removal: it reads ``HubDisplay`` directly, the
authoritative store, never the display replica.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.operations.frame_grouping import FrameAccumulator
from punt_lux.operations.models.query_ownership import SceneOwner
from punt_lux.operations.models.query_quarantine import QuarantineInfo
from punt_lux.operations.models.query_scenes import (
    FrameSummary,
    SceneList,
    SceneSummary,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.quarantine_record import QuarantineRecord
    from punt_lux.domain.hub.scene_presentation import ScenePresentation
    from punt_lux.domain.ids import SceneId
    from punt_lux.operations.frame_visibility_proxy import FrameVisibilityProxy
    from punt_lux.operations.models.inspect_scope import InspectScope

__all__ = ["SceneListing"]

logger = logging.getLogger(__name__)


@final
class SceneListing:
    """Every scene and frame in the authoritative store, grouped and summarized."""

    _display: HubDisplay
    _seen: FrameVisibilityProxy
    __slots__ = ("_display", "_seen")

    def __new__(cls, display: HubDisplay, seen: FrameVisibilityProxy) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._seen = seen
        return self

    def read(self, facts: InspectScope) -> SceneList:
        """List every scene and frame from the authoritative store.

        Includes quarantined scenes alongside live ones — quarantine is a
        replication decision, not a deletion, so introspection stays honest
        about the scenes the store still holds. Each summary carries a
        ``status`` discriminator (``"live"`` or ``"quarantined"``) and, when
        quarantined, the :class:`QuarantineInfo` record explaining why.
        Replication reads through :meth:`HubDisplay.live_scene_ids` instead,
        which excludes quarantined scenes at the source.

        ``facts`` may ask for each frame's visibility, which is the one thing
        here the Hub does not hold: where a window sits belongs to the user and
        is never replicated back (DES-088). It is proxied from the running
        display only when asked, so a bare call stays a single Hub-local read and
        never reaches around — the same bargain ``inspect_scene`` strikes for
        painted geometry.
        """
        scenes: list[SceneSummary] = []
        frames: dict[str, FrameAccumulator] = {}
        for sid in self._display.all_scene_ids():
            presentation = self._display.frames.presentation_for(sid)
            scenes.append(self._scene_summary(sid, presentation))
            self._gather(frames, presentation).add(str(sid))
        return SceneList(scenes=scenes, frames=self._frame_summaries(frames, facts))

    def quarantine_info(self, scene_id: SceneId) -> QuarantineInfo | None:
        """Return the scene's quarantine read shape, or None if not quarantined.

        Shared with ``QueryOperations.inspect_scene``, which reports the same
        record for the one scene it reads.
        """
        record: QuarantineRecord | None = self._display.quarantine_record(scene_id)
        if record is None:
            return None
        return QuarantineInfo.of(record)

    def _scene_summary(
        self, sid: SceneId, presentation: ScenePresentation
    ) -> SceneSummary:
        """Build one scene's summary, quarantined or live."""
        quarantine = self.quarantine_info(sid)
        return SceneSummary(
            scene_id=str(sid),
            local_id=self.local_id_of(sid),
            element_count=self._display.element_count(sid),
            frame_id=presentation.frame_id,
            owners=self._owners_of(sid),
            status="quarantined" if quarantine is not None else "live",
            quarantine=quarantine,
        )

    @staticmethod
    def _gather(
        frames: dict[str, FrameAccumulator], presentation: ScenePresentation
    ) -> FrameAccumulator:
        """Return the accumulator for this scene's frame, starting one if needed."""
        return frames.setdefault(
            presentation.frame_id,
            FrameAccumulator(
                title=presentation.frame_title or presentation.frame_id,
                layout=presentation.frame_layout or "tab",
            ),
        )

    def _frame_summaries(
        self, frames: dict[str, FrameAccumulator], facts: InspectScope
    ) -> list[FrameSummary]:
        """Close every accumulator, attaching the visibility ``facts`` asked for.

        The display is asked once for the whole call rather than once per frame:
        asking repeatedly would let the answer change mid-list.
        """
        seen = self._seen.of_frames(facts)
        absent = self._seen.absent(facts)
        return [acc.summary(fid, seen.get(fid, absent)) for fid, acc in frames.items()]

    def _owners_of(self, scene_id: SceneId) -> list[SceneOwner]:
        """Return the scene's distinct owners as introspection read shapes."""
        return [SceneOwner.of(owner) for owner in self._display.scene_owners(scene_id)]

    @staticmethod
    def local_id_of(scene_id: SceneId | str) -> str:
        """Return the caller's own label for a store key, composed or not.

        Every scene the ops-layer write path installs is composed (DES-086),
        so this is the caller's raw name in the common case. A key installed
        through a lower-level API directly carries no separator at all; it is
        reported as-is rather than raising, but logged — a DES-086 invariant
        violation worth knowing about, not silently absorbed. Shared with
        :class:`~punt_lux.operations.client_listing.ClientListing`, which
        strips the same composed keys for ``owned_scenes``.
        """
        try:
            return ConnectionScopedId.from_composed(str(scene_id)).local_id
        except ValueError:
            logger.warning("non-composed store key at introspection: %r", scene_id)
            return str(scene_id)
