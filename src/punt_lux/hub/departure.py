"""Departure -- what discarding one connection removed, and whose name it moved."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.hub.callback_ports import CallbackListener
    from punt_lux.kernel.connection_id import ConnectionId

__all__ = ["Departure"]


@final
@dataclass(frozen=True, slots=True)
class Departure:
    """The survivors a release retitled, and the leg the connection held, if any."""

    relabelled: frozenset[ConnectionId]
    leg: CallbackListener | None
