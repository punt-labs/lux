"""``SyncOps`` -- every synchronous Hub operation ``LuxClient.sync`` exposes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

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

if TYPE_CHECKING:
    from punt_lux.operations import Ok, OpError

__all__ = ["CallbackConvenienceOps", "SyncOps"]


@runtime_checkable
class CallbackConvenienceOps(Protocol):
    """The bare-args ``register_callback`` shape every production caller depends on.

    Distinct from :class:`~punt_lux.commands._ports.CallbackRegisterOps`, whose
    Protocol shape is ``register_callback(request, *, scope)`` for the
    in-process ``Operations`` facade. ``_RestTransport`` carries this shape
    instead, since ``applets/leg.py`` already calls it bare; see
    ``cli/callback.py``'s ``_CallbackRegisterAdapter`` for the one adapter
    between the two.
    """

    def register_callback(
        self, callback_id: str, label: str, frame_id: str | None = None
    ) -> Ok | OpError:
        """Register a menu callback; ``frame_id`` is applet-only.

        See :meth:`CallbackAccessor.register`.
        """
        ...


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
