"""FrameRemoveRequest -- everything one ``frame remove`` call needs, bundled.

``execute``/``__call__`` are called directly by two different surfaces (the
MCP tool and the library/CLI accessor); naming their shared input as one type
documents the call once instead of at each of the three call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, FrameOps
    from punt_lux.operations import Scope

__all__ = ["FrameRemoveRequest"]


@final
@dataclass(frozen=True, slots=True)
class FrameRemoveRequest:
    """The command context, the frame to remove, and the scope removing it."""

    ctx: Ctx[FrameOps]
    frame_id: str  # caller's local name; FrameRemover resolves it against ownership
    scope: Scope
