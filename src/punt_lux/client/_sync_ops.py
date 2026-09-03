"""``SyncOps`` -- every synchronous Hub operation ``LuxClient.sync`` exposes."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from punt_lux.client._callback_ops import CallbackConvenienceOps
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
    ThemeOps,
    WindowOps,
    DisplayModeOps,
    ScreenshotOps,
    Protocol,
):
    """Every synchronous Hub operation ``LuxClient.sync`` exposes at once.

    A Protocol extending every per-family Ops Protocol in ``commands/_ports.py``
    plus :class:`CallbackConvenienceOps` -- satisfied structurally by
    ``_RestTransport``, adding no new requirement on it. Lets a caller's
    ``Ctx[SceneOps]`` (or narrower) accept ``client.sync`` without ever
    importing ``_RestTransport``.
    """
