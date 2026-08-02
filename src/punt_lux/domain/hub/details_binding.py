"""The Details command's binding — how a menu click reaches the operation.

A click on ``Details`` lands in the Hub's interaction dispatch, which is domain
code and may not call the operations layer: the dependency arrow points
operations → domain and never back. So the domain states what it needs — a
renderer it can hand a connection id to — and the composition root that builds
the operations facade binds the real one.

Until something binds it, the binding holds the Null Object: a click says so in
the log and nothing else happens. That is the honest behavior for a display
clicked before luxd finished composing itself, and it keeps the dispatch free of
a ``None`` check on a collaborator that is present in every running process.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId

logger = logging.getLogger(__name__)

__all__ = ["ClientDetailsRenderer", "DetailsBinding", "NoDetailsRenderer"]


@runtime_checkable
class ClientDetailsRenderer(Protocol):
    """Shows one client's connection state — what the Details command runs."""

    def show_client_details(self, connection_id: ConnectionId) -> object:
        """Render that connection's state, returning the operation's own result."""
        ...


@final
class NoDetailsRenderer:
    """The renderer in place before the composition root binds the real one."""

    __slots__ = ()

    def show_client_details(self, connection_id: ConnectionId) -> object:
        """Report the click that arrived with nothing to answer it."""
        logger.warning(
            "Details clicked for %s before luxd bound its renderer", connection_id
        )
        return None


@final
class DetailsBinding:
    """The renderer the Hub's Details command runs, replaceable at composition."""

    _renderer: ClientDetailsRenderer
    __slots__ = ("_renderer",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._renderer = NoDetailsRenderer()
        return self

    def bind(self, renderer: ClientDetailsRenderer) -> None:
        """Install the renderer every later Details click runs.

        Last binding wins: luxd composes an operations facade for MCP and
        another for REST over the same stores, and either can answer a click.
        """
        self._renderer = renderer

    def run(self, connection_id: ConnectionId) -> None:
        """Run the Details command for one connection.

        Named for what it does rather than what it produces: a Hub-side show
        call reads as a write to the display connection, which only the
        replicator may make, and the guard holding that invariant is right to
        say so of anything here that looked like one.
        """
        self._renderer.show_client_details(connection_id)
