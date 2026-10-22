"""SceneQuarantine — the locked quarantine authority: record, lift, and notify.

Quarantine is a replication decision, not a teardown: the scene stays installed and
inspectable while the replicator stops sending it. Every read and write takes the
store lock, so a replicator that saw "not quarantined" cannot race a quarantine write
and patch a scene that has just been isolated. Lifting a quarantine runs the cleared
observers under that same lock; they must not do I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.quarantine_registry import QuarantineRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.quarantine_record import QuarantineRecord
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.ids import SceneId

__all__ = ["SceneQuarantine"]


@final
class SceneQuarantine:
    """Quarantine records for scenes, guarded by the store lock."""

    _registry: QuarantineRegistry
    _lock: StoreLock
    _cleared_observers: list[Callable[[SceneId], None]]
    __slots__ = ("_cleared_observers", "_lock", "_registry")

    def __new__(cls, lock: StoreLock) -> Self:
        self = super().__new__(cls)
        self._registry = QuarantineRegistry()
        self._lock = lock
        self._cleared_observers = []
        return self

    def quarantine(self, scene_id: SceneId, record: QuarantineRecord) -> None:
        """Quarantine ``scene_id``: stop replicating it, keep it for inspection."""
        with self._lock.write():
            self._registry.quarantine(scene_id, record)

    def is_quarantined(self, scene_id: SceneId) -> bool:
        """Return whether ``scene_id`` currently carries a quarantine record."""
        with self._lock.read():
            return self._registry.is_quarantined(scene_id)

    def quarantine_record(self, scene_id: SceneId) -> QuarantineRecord | None:
        """Return the scene's quarantine record, or None if not quarantined."""
        with self._lock.read():
            return self._registry.record_for(scene_id)

    def quarantined_ids(self) -> frozenset[SceneId]:
        """Return every quarantined scene id. Caller holds the store lock."""
        return self._registry.quarantined_ids()

    def add_quarantine_cleared_observer(
        self, observer: Callable[[SceneId], None]
    ) -> None:
        """Register a callback for quarantine-lift; runs under the lock, no I/O."""
        with self._lock.write():
            self._cleared_observers.append(observer)

    def lift(self, scene_id: SceneId) -> None:
        """Clear ``scene_id``'s quarantine and notify observers. Caller locks."""
        if not self._registry.is_quarantined(scene_id):
            return
        self._registry.clear(scene_id)
        for observer in self._cleared_observers:
            observer(scene_id)
