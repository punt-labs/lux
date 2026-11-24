"""The display state query port."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.wire.operations import DisplayStateSnapshot, OpError, Scope


@runtime_checkable
class DisplayStateOps(Protocol):
    """The ops surface this module's command reads."""

    def get_display_state(self, *, scope: Scope) -> DisplayStateSnapshot | OpError:
        """Return the caller's own widget/frame state, proxied."""
        ...
