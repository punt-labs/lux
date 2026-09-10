"""``SyncOps`` -- every synchronous Hub operation ``LuxClient.sync`` exposes."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from punt_lux.client._callback_ops import CallbackConvenienceOps
from punt_lux.client._display_link_ops import DisplayLinkOps
from punt_lux.commands._ports import (
    DisplayInfoOps,
    DisplayModeOps,
    ErrorOps,
    EventOps,
    FrameOps,
    MenuOps,
    PingOps,
    SceneOps,
    ScreenshotOps,
    SessionOps,
    ThemeOps,
    WindowOps,
)
from punt_lux.commands.display_state_get import DisplayStateOps

__all__ = ["CallbackConvenienceOps", "SyncOps"]


@runtime_checkable
class SyncOps(
    PingOps,
    SceneOps,
    FrameOps,
    MenuOps,
    SessionOps,
    CallbackConvenienceOps,
    EventOps,
    ErrorOps,
    DisplayInfoOps,
    DisplayStateOps,
    DisplayLinkOps,
    ThemeOps,
    WindowOps,
    DisplayModeOps,
    ScreenshotOps,
    Protocol,
):
    """Every synchronous Hub operation ``LuxClient.sync`` exposes at once."""
