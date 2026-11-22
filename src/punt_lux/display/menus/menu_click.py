"""Describe callback groups and clickable entries in replicated menus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.wire.model import RemoteEventHandlerInvocation
    from punt_lux.wire.model.identity import HubId

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
