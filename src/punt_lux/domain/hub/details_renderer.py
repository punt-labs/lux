"""The port the Hub's Details command arrives on, and its Null Object.

The interaction dispatch is domain code and the dependency arrow runs
operations → domain, never back. So the domain states what it needs — something
it can hand a connection id to — and the composition root binds the real one.

The port answers in the domain's own terms rather than the operations layer's
result type, for the same reason: this side cannot name an ``OpError``, and it
does not need to. Whether the click was answered is all the dispatch has to
know, and the outcome it gets back reports itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, final, runtime_checkable

from punt_lux.domain.hub.details_outcome import DetailsUnbound

if TYPE_CHECKING:
    from punt_lux.domain.hub.details_outcome import DetailsOutcome
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ClientDetailsRenderer", "NoDetailsRenderer"]


@runtime_checkable
class ClientDetailsRenderer(Protocol):
    """Shows one client's connection state — what the Details command runs."""

    def render_details(self, connection_id: ConnectionId) -> DetailsOutcome:
        """Show that connection's state, or report that there was none to show."""
        ...


@final
class NoDetailsRenderer:
    """The Null Object: a click before anything bound the real renderer."""

    __slots__ = ()

    def render_details(self, connection_id: ConnectionId) -> DetailsOutcome:
        """Answer with the outcome that says nothing was bound, and log nothing.

        The outcome carries its own line, so the click leaves exactly one — and
        one that names the reason that was actually checked.
        """
        return DetailsUnbound(connection_id)
