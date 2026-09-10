"""BackoffConfig — the clock, delay bounds, and stability bar one RespawnBackoff
paces within.

Bundled into one value object so :class:`~punt_lux.domain.hub.respawn_backoff.
RespawnBackoff`'s constructor takes a single parameter instead of several, and
so a second, independently-tuned instance — the disconnected-display backoff
in :mod:`~punt_lux.domain.hub.replicator`
(docs/architecture/display-presence-demand-driven.md §6.2) — reads as one
named value rather than positional floats a caller could transpose.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from punt_lux.domain.hub.crash_attribution import STABLE_INTERVAL

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["BackoffConfig"]

_BASE_DELAY_SECONDS = 1.0
_MAX_DELAY_SECONDS = 30.0


@final
@dataclass(frozen=True, slots=True)
class BackoffConfig:
    """One RespawnBackoff's clock, its delay's base/cap, and its reset bar."""

    clock: Callable[[], float] = time.monotonic
    base_delay: float = _BASE_DELAY_SECONDS
    max_delay: float = _MAX_DELAY_SECONDS
    stable_interval: float = STABLE_INTERVAL
