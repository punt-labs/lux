"""Settlement -- what a dial owed when it ended, and who ended it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.ids import SceneId

__all__ = ["Settlement"]


@dataclass(frozen=True, slots=True)
class Settlement:
    """The ledger a dial left when it was captured, whoever's end it was.

    ``owed`` is the scenes written to the dial whose acks never reached its ledger, in
    write order. ``acked`` says the display's ack was read on this dial at least once,
    which is what clears the suspects an earlier dial left behind. ``cause`` is the
    first cause recorded for the end, which is the one that stands.
    """

    owed: tuple[SceneId, ...]
    acked: bool
    cause: RetireCause
