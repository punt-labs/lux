"""The ops-surface Protocol the frame commands read.

Split out of :mod:`punt_lux.commands._ports` (lux-03k6): that module had
grown into a single file mixing every command family's Protocol, one class
per unrelated concern. Frame removal is its own family; giving it its own
module is the same move :mod:`punt_lux.operations.frame_removal` makes on
the implementation side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.operations import Ok, OpError, Scope

__all__ = ["FrameOps"]


@runtime_checkable
class FrameOps(Protocol):
    """The ops surface the frame commands read."""

    def remove_frame(self, frame_id: str, *, scope: Scope) -> Ok | OpError:
        """Remove the caller's own frame's content: tear down its scenes on the Hub."""
        ...
