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
"""

from __future__ import annotations

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


@final
class CrashAttribution:
    """The per-scene windowed death tally, the send mode, and the exit decision."""

    _port: QuarantinePort
    _clock: Callable[[], float]
    _mode: Literal["batching", "isolating"]
    _tallies: dict[SceneId, deque[float]]
    _last_death_at: float | None
    __slots__ = ("_clock", "_last_death_at", "_mode", "_port", "_tallies")

    def __new__(
        cls, port: QuarantinePort, clock: Callable[[], float] = time.monotonic
    ) -> Self:
        self = super().__new__(cls)
        self._port = port
        self._clock = clock
        self._mode = "batching"
        self._tallies = {}
        self._last_death_at = None
        return self

    @property
    def mode(self) -> Literal["batching", "isolating"]:
        """The replicator's current send mode."""
        return self._mode

    def is_quarantined(self, scene_id: SceneId) -> bool:
        """Return whether the store currently holds ``scene_id`` quarantined.

        A pass-through to the port, not a local cache: quarantine can also be
        lifted by an owner's re-show, which this object never observes, so the
        store's record is the only value that can never go stale.
        """
        return self._port.is_quarantined(scene_id)

    def attribute_death(self, suspect_set: frozenset[SceneId]) -> frozenset[SceneId]:
        """Attribute one Display death, now, to every scene in ``suspect_set``.

        Switches the mode to isolating (idempotent if already there) and
        quarantines any scene that reaches ``ATTRIBUTION_THRESHOLD`` inside the
        rolling window. Returns the scenes newly quarantined by this death.
        """
        now = self._clock()
        self._last_death_at = now
        self._mode = "isolating"
        newly_quarantined: set[SceneId] = set()
        for scene_id in suspect_set:
            tally = self._tallies.setdefault(scene_id, deque())
            tally.append(now)
            if self.quarantine_if_threshold(scene_id):
                newly_quarantined.add(scene_id)
        return frozenset(newly_quarantined)

    def quarantine_if_threshold(self, scene_id: SceneId) -> bool:
        """Quarantine ``scene_id`` if its windowed tally reached the threshold.

        Returns whether this call quarantined it. Idempotent-safe against a
        scene the port already holds quarantined — the guard is on the tally,
        not on the port's own state, since the port is the one place quarantine
        can also be lifted from.
        """
        tally = self._tallies.get(scene_id)
        if tally is None:
            return False
        now = self._clock()
        self._prune(tally, now)
        if len(tally) < ATTRIBUTION_THRESHOLD:
            return False
        record = QuarantineRecord(death_count=len(tally), last_death_at=now)
        self._port.quarantine(scene_id, record)
        return True

    def exit_isolation_if_stable(self) -> bool:
        """Return to batching once the Display served ``STABLE_INTERVAL`` death-free.

        Never on one clean pass and never on a quarantine — only a death-free
        stable interval, which is what lets an intermittently poisonous scene
        be pursued across its clean renders instead of escaping isolation the
        moment it happens to render cleanly. Returns whether the exit fired.
        """
        if self._mode == "batching":
            return False
        now = self._clock()
        if (
            self._last_death_at is not None
            and now - self._last_death_at < STABLE_INTERVAL
        ):
            return False
        self._mode = "batching"
        return True

    @staticmethod
    def _prune(tally: deque[float], now: float) -> None:
        """Drop attributed deaths older than ``ATTRIBUTION_WINDOW`` from ``tally``."""
        while tally and now - tally[0] > ATTRIBUTION_WINDOW:
            tally.popleft()
