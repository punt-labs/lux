"""MenuArming — the menu_set precondition: identified, inbox armed.

Admit an identified session (arming its inbox writer) and refuse an anonymous or
unregistered one — nothing anonymous owns a menu item.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.menu_arming import MenuArming


@final
class _WriterSpy:
    """Records the connections whose inbox writer was armed."""

    armed: list[ConnectionId]
    __slots__ = ("armed",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.armed = []
        return self

    def __call__(self, connection_id: ConnectionId) -> None:
        self.armed.append(connection_id)


def test_admits_an_identified_session_and_arms_its_inbox() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("agent")
    clients.record(conn, ClientIdentity(kind="mcp-session", name="agent"))
    writer = _WriterSpy()

    assert MenuArming(clients, writer).admit(conn) is True
    assert writer.armed == [conn]


def test_refuses_an_anonymous_session_and_arms_nothing() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("anon")
    clients.record(conn)  # registered, but never identified
    writer = _WriterSpy()

    assert MenuArming(clients, writer).admit(conn) is False
    assert writer.armed == []


def test_refuses_an_unregistered_session() -> None:
    writer = _WriterSpy()
    admitted = MenuArming(HubClientRegistry(), writer).admit(ConnectionId("never"))
    assert admitted is False
    assert writer.armed == []
