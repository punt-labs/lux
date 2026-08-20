"""CrashAttribution — the windowed death tally that quarantines a poison scene.

Owns the whole attribution rule from display-crash-quarantine.md Question 1: the
per-scene windowed tally, the ``ATTRIBUTION_THRESHOLD``, the batching/isolation
send mode, and the isolation-exit decision. Every Display death is attributed to
its suspect set — the whole batch in batching mode, a probed singleton in
isolation mode — so a scene that only ever crashes while coalesced with others
cannot escape the tally. A scene reaching ``ATTRIBUTION_THRESHOLD`` attributed
deaths within the rolling ``ATTRIBUTION_WINDOW`` is quarantined through the
:class:`QuarantinePort` this object is given, and isolation is left only after a
death-free ``STABLE_INTERVAL`` — never on one clean pass — so an intermittently
poisonous scene is pursued across its clean renders instead of escaping the
moment it happens to render cleanly.

Internally thread-safe: the tally, mode, and last-death timestamp all live under
one lock. The replicator thread calls ``attribute_death``/``mode``/
``exit_isolation_if_stable``; MCP tool threads (via ``HubDisplay``'s
quarantine-cleared observer wiring) call ``clear_tally`` when an owner's
re-show or removal lifts a quarantine. Serializing every mutation on one lock
keeps the "must not re-quarantine off one fresh death" invariant crossable by
either thread.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Literal, Protocol, Self, final, runtime_checkable

from punt_lux.domain.hub.quarantine_record import QuarantineRecord

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.ids import SceneId

__all__ = [
    "ATTRIBUTION_THRESHOLD",
    "ATTRIBUTION_WINDOW",
    "STABLE_INTERVAL",
    "CrashAttribution",
]

# The number of attributed deaths a scene must cause before it is quarantined.
# Two, not one: a single death admits a non-scene cause (memory pressure, a
# driver fault) that coincided with a render, and must not quarantine a scene.
ATTRIBUTION_THRESHOLD = 2

# Scopes "repeated" so two deaths separated by hours are not fused into a false
# attribution; comfortably longer than the observed crash-respawn period so a
# real poison scene reaches the threshold well inside one window.
ATTRIBUTION_WINDOW = 60.0

# The isolation-exit interval, tied to (and at least) ATTRIBUTION_WINDOW: an
# innocent scene's lone batched increment always ages out of the window before
# a second batched increment could land, which is what makes an innocent scene
# never being quarantined provable rather than merely likely.
STABLE_INTERVAL = 60.0


@runtime_checkable
class QuarantinePort(Protocol):
    """The store operations attribution needs — satisfied by ``HubDisplay``."""

    def quarantine(self, scene_id: SceneId, record: QuarantineRecord) -> None:
        """Quarantine ``scene_id`` on the store's scene entry."""

    def is_quarantined(self, scene_id: SceneId) -> bool:
        """Return whether the store currently holds ``scene_id`` quarantined."""
        ...

    def add_quarantine_cleared_observer(
        self, observer: Callable[[SceneId], None]
    ) -> None:
        """Register a callback fired whenever a scene's quarantine is lifted.

        The observer runs synchronously under the store lock, so it must not
        block; ``CrashAttribution.clear_tally`` is designed for exactly that
        use so a lifted quarantine also resets the scene's tally, and a scene
        that crashes again after being fixed needs the full threshold before
        being re-quarantined (never off one fresh death).
        """


@final
class CrashAttribution:
    """The per-scene windowed death tally, the send mode, and the exit decision."""

    _port: QuarantinePort
    _clock: Callable[[], float]
    _lock: threading.Lock
    _mode: Literal["batching", "isolating"]
    _tallies: dict[SceneId, deque[float]]
    _last_death_at: float | None
    __slots__ = ("_clock", "_last_death_at", "_lock", "_mode", "_port", "_tallies")

    def __new__(
        cls, port: QuarantinePort, clock: Callable[[], float] = time.monotonic
    ) -> Self:
        self = super().__new__(cls)
        self._port = port
        self._clock = clock
        self._lock = threading.Lock()
        self._mode = "batching"
        self._tallies = {}
        self._last_death_at = None
        return self

    @property
    def mode(self) -> Literal["batching", "isolating"]:
        """The replicator's current send mode, read under the lock."""
        with self._lock:
            return self._mode

    def is_quarantined(self, scene_id: SceneId) -> bool:
        """Return whether the store currently holds ``scene_id`` quarantined.

        A pass-through to the port, not a local cache: quarantine can also be
        lifted by an owner's re-show, which this object never observes, so the
        store's record is the only value that can never go stale.
        """
        return self._port.is_quarantined(scene_id)

    def attribute_death(
        self,
        suspect_set: frozenset[SceneId],
        *,
        render_error: str | None = None,
    ) -> frozenset[SceneId]:
        """Attribute one Display death, now, to every scene in ``suspect_set``.

        Switches the mode to isolating (idempotent if already there) and
        quarantines any scene that reaches ``ATTRIBUTION_THRESHOLD`` inside the
        rolling window. Returns the scenes newly quarantined by this death.

        ``render_error`` is the message of the exception that surfaced the
        death — the ``OSError``/``BlockingIOError`` the replicator caught from
        the failed send or probe. Any scene the death quarantines carries it
        on its :class:`QuarantineRecord` so an agent whose scene later goes
        dark sees WHY, not just that. None is honest for callers that have no
        exception to attribute (a synthetic priming attribute in tests, etc.).

        The empty suspect set is a valid input — a menu-attributed death lands
        here with no scene in flight (see ``HubReplicator._attempt``), which
        still trips isolation but blames no scene.

        Tally updates happen under this class's lock; the ``port.quarantine``
        callback fires only after the lock is released, so this class never
        holds two locks at once. Necessary because ``clear_tally`` runs from
        the store's quarantine-cleared observer under the store lock — the
        reverse order (store lock while port.quarantine is holding this lock)
        would deadlock a replicator-thread attribute against a caller-thread
        ``replace_scene``.
        """
        now = self._clock()
        to_quarantine = self._record_death(suspect_set, now, render_error)
        for scene_id, record in to_quarantine:
            self._port.quarantine(scene_id, record)
        return frozenset(scene_id for scene_id, _ in to_quarantine)

    def _record_death(
        self,
        suspect_set: frozenset[SceneId],
        now: float,
        render_error: str | None,
    ) -> list[tuple[SceneId, QuarantineRecord]]:
        """Update tallies and mode under the lock; return records to quarantine."""
        to_quarantine: list[tuple[SceneId, QuarantineRecord]] = []
        with self._lock:
            self._last_death_at = now
            self._mode = "isolating"
            for scene_id in suspect_set:
                tally = self._tallies.setdefault(scene_id, deque())
                tally.append(now)
                self._prune(tally, now)
                if len(tally) >= ATTRIBUTION_THRESHOLD:
                    to_quarantine.append(
                        (
                            scene_id,
                            QuarantineRecord(
                                death_count=len(tally),
                                last_death_at=now,
                                render_error=render_error,
                            ),
                        )
                    )
        return to_quarantine

    def quarantine_if_threshold(self, scene_id: SceneId) -> bool:
        """Quarantine ``scene_id`` if its windowed tally reached the threshold.

        Returns whether this call quarantined it. Idempotent-safe against a
        scene the port already holds quarantined — the guard is on the tally,
        not on the port's own state, since the port is the one place quarantine
        can also be lifted from. The ``port.quarantine`` call fires outside
        this class's lock, matching :meth:`attribute_death`'s discipline.
        """
        now = self._clock()
        record: QuarantineRecord | None
        with self._lock:
            tally = self._tallies.get(scene_id)
            if tally is None:
                return False
            self._prune(tally, now)
            if len(tally) < ATTRIBUTION_THRESHOLD:
                return False
            record = QuarantineRecord(death_count=len(tally), last_death_at=now)
        self._port.quarantine(scene_id, record)
        return True

    def clear_tally(self, scene_id: SceneId) -> None:
        """Forget every attributed death for ``scene_id``.

        Called from :class:`~punt_lux.domain.hub.hub_display.HubDisplay`'s
        quarantine-cleared observer wiring so an owner's re-show (which lifts
        quarantine) also resets the tally — otherwise a scene that just
        recovered would re-quarantine off a *single* fresh death, since its
        old in-window tally would still be at the threshold minus one.
        """
        with self._lock:
            self._tallies.pop(scene_id, None)

    def exit_isolation_if_stable(self) -> bool:
        """Return to batching once the Display served ``STABLE_INTERVAL`` death-free.

        Never on one clean pass and never on a quarantine — only a death-free
        stable interval, which is what lets an intermittently poisonous scene
        be pursued across its clean renders instead of escaping isolation the
        moment it happens to render cleanly. Returns whether the exit fired.
        """
        now = self._clock()
        with self._lock:
            if self._mode == "batching":
                return False
            if (
                self._last_death_at is not None
                and now - self._last_death_at < STABLE_INTERVAL
            ):
                return False
            self._mode = "batching"
            # Free the per-scene tallies: STABLE_INTERVAL >= ATTRIBUTION_WINDOW
            # means every entry left in every tally is already stale (past the
            # window), so a fresh episode's attribution decisions are
            # unaffected. Clearing them here keeps memory from growing without
            # bound after batched deaths that touched many scenes.
            self._tallies.clear()
            self._last_death_at = None
            return True

    @staticmethod
    def _prune(tally: deque[float], now: float) -> None:
        """Drop attributed deaths older than ``ATTRIBUTION_WINDOW`` from ``tally``."""
        while tally and now - tally[0] > ATTRIBUTION_WINDOW:
            tally.popleft()
