"""The click-time value types a wire menu threads through activation: the
callbacks a click fires (:class:`MenuHandlers`) and what one clickable line
reports about itself (:class:`ClickTarget`), bundled so every method in
:meth:`Submenu.from_wire`'s recursion takes a handful of parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.identity import HubId
    from punt_lux.protocol import RemoteEventHandlerInvocation

__all__ = ["ClickTarget", "MenuHandlers"]

type EmitEvent = Callable[[RemoteEventHandlerInvocation], None]
type RaiseFrame = Callable[[str, HubId], None]


@dataclass(frozen=True, slots=True)
class MenuHandlers:
    """Click callbacks (emit, raise) plus the owning :class:`HubId` they scope to."""

    emit: EmitEvent
    raise_frame: RaiseFrame
    hub: HubId


@dataclass(frozen=True, slots=True)
class ClickTarget:
    """What one clickable line reports: its labels, id, and frame."""

    menu_label: str
    item_label: str
    item_id: str
    frame_id: str | None
