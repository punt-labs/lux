"""The click-time value types a wire menu threads through activation.

Two things travel together through every level of :meth:`Submenu.from_wire`'s
recursion: the callbacks a click fires (:class:`MenuHandlers`) and what one
clickable line reports about itself (:class:`ClickTarget`). Bundling each into
its own frozen value class keeps every method in that recursion to a handful
of parameters, rather than threading four-to-six loose arguments by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.protocol import RemoteEventHandlerInvocation

__all__ = ["ClickTarget", "MenuHandlers"]

type EmitEvent = Callable[[RemoteEventHandlerInvocation], None]
type RaiseFrame = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class MenuHandlers:
    """The two click callbacks every wire entry threads through: emit, raise."""

    emit: EmitEvent
    raise_frame: RaiseFrame


@dataclass(frozen=True, slots=True)
class ClickTarget:
    """What one clickable line reports on activation: its labels, id, and frame."""

    menu_label: str
    item_label: str
    item_id: str
    frame_id: str | None
