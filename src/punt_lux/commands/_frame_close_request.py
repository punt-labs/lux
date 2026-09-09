"""FrameCloseRequest -- everything one ``frame close`` call needs, bundled.

``execute``/``__call__`` are called directly by two different surfaces (the
MCP tool and the library/CLI accessor); naming their shared input as one type
documents the call once instead of at each of the three call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from punt_lux.commands._frame_target import FrameTarget

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, FrameOps
    from punt_lux.operations import Scope

__all__ = ["FrameCloseRequest"]


@final
@dataclass(frozen=True, slots=True)
class FrameCloseRequest:
    """The command context, the frame to close, and the scope closing it."""

    ctx: Ctx[FrameOps]
    frame_id: str  # caller's local name; FrameCloser resolves it against ownership
    scope: Scope

    @property
    def target(self) -> FrameTarget:
        """The ops-layer ``FrameTarget`` this request resolves to."""
        return FrameTarget(self.frame_id, self.scope)
