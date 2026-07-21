"""DirtySignal — the changed-scene set, cleared flag, and stop flag under one lock.

The replicator worker sleeps on this until a mutation marks a scene dirty, a
clear is requested, or a stop is asked. ``mark_dirty`` / ``mark_cleared`` are
queue-only — they touch memory and notify, never any I/O — so a mutation tool
returns the instant the store is updated. ``wait_and_drain`` is the worker's
side: it blocks until there is work or a stop, coalesces a burst into one cycle,
then takes the whole set atomically as a ``DrainedBatch``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from punt_lux.domain.ids import SceneId

__all__ = ["DirtySignal", "DrainedBatch", "MenuPush"]


@final
@dataclass(frozen=True, slots=True)
class MenuPush:
    """The whole menu state to resend: the agent menu bar and the tool items.

    The ``bar`` is the agent-defined menu bar (rendered from ``MenuMessage``); the
    ``items`` are the registered tool items (rendered in the World menu from
    ``RegisterMenuMessage``). Both are wire dicts — the display's own untyped menu
    payloads, built by the operation from typed models (PY-TS-14 wire boundary).
    A resend replaces the whole of each, so only the newest push survives a burst.
    """

    bar: tuple[Mapping[str, object], ...]
    items: tuple[Mapping[str, object], ...]


@final
@dataclass(frozen=True, slots=True)
class DrainedBatch:
    """One cycle's work: coalesced scenes, a pending clear, a menu push, and stop."""

    scenes: frozenset[SceneId]
    cleared: bool
    shutting: bool
    menus: MenuPush | None = None

    @property
    def has_work(self) -> bool:
        """Whether this cycle has anything to push."""
        return bool(self.scenes) or self.cleared or self.menus is not None


@final
class DirtySignal:
    """The changed-scene set, cleared flag, and stop flag under one condition.

    ``mark_dirty`` / ``mark_cleared`` are queue-only — they touch memory and
    notify, never any I/O — so a mutation tool returns the instant the store is
    updated. ``wait_and_drain`` is the worker's side: it blocks until there is
    work or a stop, coalesces a burst, then takes the whole set atomically.
    """

    _cond: threading.Condition
    _dirty: set[SceneId]
    _cleared: bool
    _shutting: bool
    _menus: MenuPush | None
    __slots__ = ("_cleared", "_cond", "_dirty", "_menus", "_shutting")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cond = threading.Condition()
        self._dirty = set()
        self._cleared = False
        self._shutting = False
        self._menus = None
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Record a changed scene and wake the worker. Queue-only, no I/O."""
        with self._cond:
            self._dirty.add(scene_id)
            self._cond.notify()

    def mark_cleared(self) -> None:
        """Record that the screen was cleared and wake the worker. No I/O."""
        with self._cond:
            self._cleared = True
            self._cond.notify()

    def mark_menus(
        self,
        bar: Sequence[Mapping[str, object]],
        items: Sequence[Mapping[str, object]],
    ) -> None:
        """Record the latest menu state to push and wake the worker. No I/O.

        Coalesces like the cleared flag: only the newest menu state survives a
        burst, since a resend replaces the whole bar and item set anyway.
        """
        with self._cond:
            self._menus = MenuPush(bar=tuple(bar), items=tuple(items))
            self._cond.notify()

    def add_all(self, scenes: Iterable[SceneId]) -> None:
        """Re-mark a set of scenes dirty — the recovery re-mark after a respawn."""
        with self._cond:
            self._dirty.update(scenes)
            self._cond.notify()

    def request_stop(self) -> None:
        """Ask the worker to flush what is pending and stop."""
        with self._cond:
            self._shutting = True
            self._cond.notify()

    @property
    def is_shutting(self) -> bool:
        """Whether a stop has been requested — latched true once asked.

        This is the single source of the stop fact. The replicator asks it to
        reject a start after a stop, so the flag that makes the worker exit and
        the flag that forbids a restart can never disagree.
        """
        with self._cond:
            return self._shutting

    def wait_and_drain(self, coalesce_seconds: float) -> DrainedBatch:
        """Block until there is work or a stop, coalesce a burst, then drain.

        Returns the whole changed set and the cleared flag together, resetting
        both, so a mark that lands after the drain is carried to the next cycle.
        """
        with self._cond:
            while (
                not self._dirty
                and not self._cleared
                and self._menus is None
                and not self._shutting
            ):
                self._cond.wait()
            if (
                self._shutting
                and not self._dirty
                and not self._cleared
                and self._menus is None
            ):
                return DrainedBatch(frozenset(), cleared=False, shutting=True)
            self._cond.wait(coalesce_seconds)
            batch = DrainedBatch(
                frozenset(self._dirty),
                cleared=self._cleared,
                shutting=self._shutting,
                menus=self._menus,
            )
            self._dirty.clear()
            self._cleared = False
            self._menus = None
            return batch
