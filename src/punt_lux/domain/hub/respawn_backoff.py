"""RespawnBackoff — paces successive Display respawns, apart from send retry.

A poison scene can crash the Display several times before
:class:`~punt_lux.domain.hub.crash_attribution.CrashAttribution` quarantines it.
Between the first death and quarantine, each attributed death triggers a
respawn, and each respawn opens a fresh window that steals macOS keyboard
focus (display-crash-quarantine.md Question 3/4). This object paces those
respawns so the pre-quarantine deaths are a slowing trickle, not a rapid burst.

Deliberately not the send-retry backoff already in
:mod:`~punt_lux.domain.hub.replicator` (``_BASE_BACKOFF_SECONDS`` /
``_MAX_BACKOFF_SECONDS``, reset on any clean *send*): that reset condition
fires too eagerly under isolation mode, where an innocent scene's clean send
would reset a shared counter mid-episode. This backoff resets only once the
Display has demonstrably served without a death for
:data:`~punt_lux.domain.hub.crash_attribution.STABLE_INTERVAL` — the same
stability bar isolation-exit uses — never on a clean send.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.crash_attribution import STABLE_INTERVAL

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["RespawnBackoff"]

_BASE_DELAY_SECONDS = 1.0
_MAX_DELAY_SECONDS = 30.0


@final
class RespawnBackoff:
    """Own the respawn delay's growth and its serve-stably reset."""

    _clock: Callable[[], float]
    _delay: float
    _last_respawn_at: float | None
    __slots__ = ("_clock", "_delay", "_last_respawn_at")

    def __new__(cls, clock: Callable[[], float] = time.monotonic) -> Self:
        self = super().__new__(cls)
        self._clock = clock
        self._delay = _BASE_DELAY_SECONDS
        self._last_respawn_at = None
        return self

    def note_respawn(self) -> float:
        """Record a respawn now; return the delay to wait before it.

        The delay is returned *before* it grows, so the caller sleeps the
        current pacing and the next respawn is paced further out.
        """
        delay = self._delay
        self._delay = min(self._delay * 2, _MAX_DELAY_SECONDS)
        self._last_respawn_at = self._clock()
        return delay

    def reset_if_stable(self) -> bool:
        """Reset the delay to base once the Display served a stable interval.

        Only fires ``STABLE_INTERVAL`` after the *last* respawn with no
        further respawn in between — a display that keeps dying keeps its
        backoff climbing. Returns whether the reset fired.
        """
        if self._last_respawn_at is None:
            return False
        if self._clock() - self._last_respawn_at < STABLE_INTERVAL:
            return False
        self._delay = _BASE_DELAY_SECONDS
        self._last_respawn_at = None
        return True
