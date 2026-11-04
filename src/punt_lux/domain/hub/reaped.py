"""Reaped -- what one sweep of lapsed leases removed, and whose name it moved."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId

__all__ = ["Reaped"]


@final
@dataclass(frozen=True, slots=True)
class Reaped:
    """What one sweep of lapsed leases removed, and whose name it moved.

    ``relabelled`` are the survivors that took over a base name the lapsed
    connections freed: their windows must be retitled.
    """

    lapsed: frozenset[ConnectionId]
    relabelled: frozenset[ConnectionId]

    def __post_init__(self) -> None:
        """Only a survivor can be retitled: the lapsed are gone."""
        departed = self.lapsed & self.relabelled
        if departed:
            msg = f"a lapsed connection cannot be relabelled: {sorted(departed)!r}"
            raise ValueError(msg)
