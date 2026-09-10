"""RespawnBackoff — paces successive Display respawns, apart from send retry.

A poison scene can crash the Display several times before
:class:`~punt_lux.domain.hub.crash_attribution.CrashAttribution` quarantines
it. Each attributed death triggers a respawn, and each respawn opens a fresh
window that steals macOS keyboard focus (display-crash-quarantine.md Question
3/4) — this paces those into a slowing trickle, not a rapid burst.

Deliberately not the send-retry backoff already in
:mod:`~punt_lux.domain.hub.replicator` (reset on any clean *send*, which fires
too eagerly here — an innocent scene's send would reset a shared counter
mid-episode). This resets only once the Display has served a death-free
stable interval. Pacing is a
:class:`~punt_lux.domain.hub.backoff_config.BackoffConfig`, so a second,
independently-tuned instance can pace the disconnected-display retry too.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.backoff_config import BackoffConfig

__all__ = ["RespawnBackoff"]

# Frozen and shared, so a call-free default satisfies ruff B008.
_DEFAULT_CONFIG = BackoffConfig()


@final
class RespawnBackoff:
    """Own the respawn delay's growth and its serve-stably reset."""

    _config: BackoffConfig
    _delay: float
    _last_respawn_at: float | None
    __slots__ = ("_config", "_delay", "_last_respawn_at")

    def __new__(cls, config: BackoffConfig = _DEFAULT_CONFIG) -> Self:
        self = super().__new__(cls)
        self._config = config
        self._delay = config.base_delay
        self._last_respawn_at = None
        return self

    @property
    def current_delay(self) -> float:
        """Return the pending delay ``note_respawn`` would apply — read-only."""
        return self._delay

    def note_respawn(self) -> float:
        """Record a respawn now; return the delay to wait before it.

        The delay is returned *before* it grows, so the caller sleeps the
        current pacing and the next respawn is paced further out.
        """
        delay = self._delay
        self._delay = min(self._delay * 2, self._config.max_delay)
        self._last_respawn_at = self._config.clock()
        return delay

    def reset_if_stable(self) -> bool:
        """Reset the delay to base once the Display served a stable interval.

        Only fires ``config.stable_interval`` after the *last* respawn with no
        further respawn in between — a display that keeps dying keeps its
        backoff climbing. Returns whether the reset fired.
        """
        if self._last_respawn_at is None:
            return False
        if self._config.clock() - self._last_respawn_at < self._config.stable_interval:
            return False
        self._delay = self._config.base_delay
        self._last_respawn_at = None
        return True
