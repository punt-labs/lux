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
    """The two-arg ``register_callback`` shape every production caller depends on.

    Distinct from :class:`~punt_lux.commands._ports.CallbackRegisterOps`, whose
    Protocol shape is ``register_callback(request, *, scope)`` -- what the
    in-process ``Operations`` facade needs. ``_RestTransport`` carries this
    convenience shape instead, because ``applets/leg.py`` already depends on
    calling it with a bare ``(callback_id, label)`` pair. The two signatures
    do not unify without either breaking that caller or adapting one shape to
    the other -- see ``cli/callback.py``'s ``_CallbackRegisterAdapter``, the
    one place that needs the Protocol shape over REST.
    """

    def register_callback(self, callback_id: str, label: str) -> Ok | OpError:
        """Register a menu callback for this identity."""
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
    ``_RestTransport`` purely because that class already has every one of
    these methods; extending this Protocol adds no new requirement on it. Its
    purpose is narrower than "expose the transport": it lets a caller's
    ``Ctx[SceneOps]`` (or ``Ctx[MenuOps]``, or a narrower composite like
    ``applets.board_ops.BoardOps``) accept ``client.sync`` without that caller
    ever importing ``_RestTransport``.
    """
