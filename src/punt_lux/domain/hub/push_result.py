"""PushResult -- what one push of a drained batch did."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.domain.ids import SceneId

__all__ = ["PushResult"]


@dataclass(frozen=True, slots=True)
class PushResult:
    """What one push did: the scenes it found empty, and the ones it left unsent."""

    emptied: tuple[SceneId, ...]  # reclaim candidates, once the cycle is clean
    deferred: tuple[SceneId, ...] = ()  # to queue again: sent unproved, or not sent
