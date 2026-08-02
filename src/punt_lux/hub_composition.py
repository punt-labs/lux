"""luxd's composition root — the one wiring its surfaces are built from.

luxd serves MCP and REST out of one process over one set of Hub singletons, and
each surface used to wire that set itself: the same ports, the same facade call,
the same Details binding, written twice. Two copies of a wiring recipe drift, and
a surface wired differently from its sibling answers differently.

So the recipe lives here once and each surface asks for what it needs. This is
the only place that reaches the process singletons; nothing under ``operations/``
does, which is what keeps the engine constructible in a test from fakes alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from punt_lux.domain.hub import client_registry, hub, hub_display
from punt_lux.domain.hub.details_instance import hub_client_details
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, next_event
from punt_lux.domain.hub.replicator_instance import (
    hub_callback_router,
    hub_menu_registry,
    hub_replicator,
)
from punt_lux.operations import HubPorts, Operations
from punt_lux.operations.client_details_port import ClientDetailsPort
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.paths import DisplayPaths

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort

__all__ = ["HubComposition"]


@final
class HubComposition:
    """Wires luxd's Hub singletons into the collaborators a surface is given."""

    __slots__ = ()

    @classmethod
    def operations(cls) -> Operations:
        """Compose the operations facade every surface calls."""
        return Operations.for_store(
            hub_display,
            hub_replicator,
            hub=hub,
            client_registry=client_registry,
            menu_registry=hub_menu_registry,
            callback_router=hub_callback_router,
            ports=cls.ports(),
        )

    @classmethod
    def bind_client_details(cls) -> None:
        """Bind the Details command the Hub's interaction dispatch runs.

        A click lands in the domain layer, which may not call operations, so the
        process binds the renderer here. Details is not a facade capability — it
        is keyed by a ``ConnectionId`` and writes a scene owned by another
        connection — so it is built from the store and ports directly.
        """
        hub_client_details.bind(
            ClientDetailsPort.for_store(
                hub_display, hub_replicator, hub=hub, ports=cls.ports()
            )
        )

    @classmethod
    def ports(cls) -> HubPorts:
        """Bundle the Hub collaborators — element decode, inbox, display."""
        return HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=ensure_writer,
            next_event=next_event,
            display_port=cls.display_port(),
        )

    @staticmethod
    def display_port() -> DisplayPort:
        """Build luxd's one bounded connection to the display for proxied ops."""
        return HubDisplayConnection(
            is_running=lambda: DisplayPaths().is_running(),
            clients=client_registry,
        )
