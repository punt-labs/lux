"""The Details command's binding — how a menu click reaches the operation.

A click on ``Details`` lands in the Hub's interaction dispatch, which is domain
code and may not call the operations layer: the dependency arrow points
operations → domain and never back. So the domain states what it needs — a
renderer it can hand a connection id to — and the composition root that builds
that renderer binds the real one.

Until something binds it, the binding holds the Null Object: a click says so in
the log and nothing else happens. That is the honest behavior for a display
clicked before luxd finished composing itself, and it keeps the dispatch free of
a ``None`` check on a collaborator that is present in every running process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.details_renderer import NoDetailsRenderer

if TYPE_CHECKING:
    from punt_lux.domain.hub.details_renderer import ClientDetailsRenderer
    from punt_lux.domain.ids import ConnectionId

__all__ = ["DetailsBinding"]


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

        Last binding wins: luxd composes one renderer at the MCP root and
        another at the REST root over the same stores, and either can answer.
        """
        self._renderer = renderer

    def run(self, connection_id: ConnectionId) -> None:
        """Run the Details command for one connection and let it report itself.

        Named for what it does rather than what it produces: a Hub-side show
        call reads as a write to the display connection, which only the
        replicator may make, and the guard holding that invariant is right to
        say so of anything here that looked like one.
        """
        self._renderer.render_details(connection_id).reported()
