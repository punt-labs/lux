"""The click-time value types a wire menu threads through activation: the
callbacks a click fires (:class:`MenuHandlers`) and what one clickable line
reports about itself (:class:`ClickTarget`), bundled so every method in
:meth:`Submenu.from_wire`'s recursion takes a handful of parameters."""

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
    """The click callbacks (emit, raise) plus the ``HubId.wire_token`` this
    menu tree replicates from -- so a scene-less click names its Hub."""

    emit: EmitEvent
    raise_frame: RaiseFrame
    hub_token: str


@dataclass(frozen=True, slots=True)
class ClickTarget:
    """What one clickable line reports: its labels, id, and frame."""

    menu_label: str
    item_label: str
    item_id: str
    frame_id: str | None
