"""FrameTarget -- the frame to close and the scope closing it, at the ops layer.

Distinct from :class:`~punt_lux.commands._frame_close_request.FrameCloseRequest`
(the command-layer bundle, which also carries the caller's ``Ctx``): every
``FrameOps.close_frame`` implementation -- the in-process facade, the REST
transport, a bare REST route with no ``Ctx`` to offer -- only ever needs the
frame and the scope, never the command context that dispatched the call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.operations import Scope

__all__ = ["FrameTarget"]


@final
@dataclass(frozen=True, slots=True)
class FrameTarget:
    """The frame to close, and the scope closing it."""

    frame_id: str  # caller's local name; FrameCloser resolves it against ownership
    scope: Scope
