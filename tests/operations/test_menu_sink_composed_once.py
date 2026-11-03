"""The Hub has one menu sink, however many surfaces compose the facade over it.

luxd composes the operations facade once per surface (MCP, REST) over the same
store. Each composition presents the lifecycle with a menu sink, and a session
armed between two compositions must still have exactly one sink bound, so its
departure marks the menus once.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId
from punt_lux.hub_composition import HubComposition
from punt_lux.operations import Operations
from punt_lux.operations.menus import MenuDepartureSink
from tests.rest._fakes import Recorder


@final
class _Hub:
    """One store whose facade can be composed any number of times."""

    factory: HubStoreFactory
    replicator: Recorder
    menu_registry: HubMenuRegistry

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.factory = HubStoreFactory()
        self.replicator = Recorder()
        self.menu_registry = HubMenuRegistry(self.factory.clients)
        return self

    def compose(self) -> Operations:
        clients = self.factory.clients
        return Operations.for_store(
            self.factory.display,
            self.replicator,
            lifecycle=self.factory.lifecycle,
            clients=clients,
            hub=Hub(),
            menu_registry=self.menu_registry,
            callback_router=CallbackRouter(clients),
            callback_menus=CallbackMenuReplica(clients),
            ports=HubComposition.ports(),
        )

    def departure_marks(self, conn: ConnectionId) -> int:
        before = self.replicator.menus
        self.factory.lifecycle.depart(conn)
        return self.replicator.menus - before


def _agent() -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


def test_two_compositions_with_a_session_armed_between_fire_one_sink() -> None:
    hub = _Hub()
    hub.compose()
    conn = ConnectionId("agent")
    hub.factory.lifecycle.identify(conn, _agent(), UNOBSERVED)
    hub.compose()
    relabelled = ClientIdentity(kind="mcp-session", name="claude", repo="/w/other")
    hub.factory.lifecycle.identify(conn, relabelled, UNOBSERVED)  # a revision re-arms

    assert hub.departure_marks(conn) == 1


def test_sinks_over_the_same_registry_and_replicator_are_equal() -> None:
    hub = _Hub()
    first = MenuDepartureSink(hub.menu_registry, hub.replicator)
    second = MenuDepartureSink(hub.menu_registry, hub.replicator)

    assert (first == second, hash(first) == hash(second)) == (True, True)


def test_sinks_over_different_replicators_are_two_sinks() -> None:
    hub = _Hub()
    first = MenuDepartureSink(hub.menu_registry, hub.replicator)
    other = MenuDepartureSink(hub.menu_registry, Recorder())

    assert first != other
