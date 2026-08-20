"""QuarantineRegistry — ``SceneId -> QuarantineRecord`` for quarantined scenes.

Sibling to :class:`~punt_lux.domain.hub.scene_presentation.ScenePresentationRegistry`:
one small dict-backed registry per concern, composed into ``HubDisplay`` rather
than folded into a bigger store. A scene absent from this registry is not
quarantined — that absence is the documented contract, not a value the type
system gave up modelling (PY-TS-14).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.quarantine_record import QuarantineRecord
    from punt_lux.domain.ids import SceneId

__all__ = ["QuarantineRegistry"]


@final
class QuarantineRegistry:
    """``SceneId -> QuarantineRecord`` for every currently-quarantined scene."""

    _records: dict[SceneId, QuarantineRecord]
    __slots__ = ("_records",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._records = {}
        return self

    def quarantine(self, scene_id: SceneId, record: QuarantineRecord) -> None:
        """Quarantine ``scene_id``, overwriting any prior record for it."""
        self._records[scene_id] = record

    def clear(self, scene_id: SceneId) -> None:
        """Lift ``scene_id``'s quarantine. No-op if it was not quarantined."""
        self._records.pop(scene_id, None)

    def record_for(self, scene_id: SceneId) -> QuarantineRecord | None:
        """Return the scene's record, or None — absence documents "not quarantined"."""
        return self._records.get(scene_id)

    def is_quarantined(self, scene_id: SceneId) -> bool:
        """Return whether ``scene_id`` currently carries a quarantine record."""
        return scene_id in self._records

    def quarantined_ids(self) -> frozenset[SceneId]:
        """Return every currently-quarantined scene id."""
        return frozenset(self._records)
