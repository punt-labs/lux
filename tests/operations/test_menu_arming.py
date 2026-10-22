"""MenuArming — the menu_set precondition: identified, inbox armed.

Admit an identified session (arming its inbox writer and the Hub's shared menu
sink) and refuse an anonymous or unregistered one — nothing anonymous owns a menu
item.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.null_dirty_marker import NullDirtyMarker
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.menu_arming import MenuArming
from punt_lux.operations.menu_arming_deps import MenuArmingDeps


@final
class _CallSpy:
    """Records the connections it was called for — an inbox or departure arm."""

    armed: list[ConnectionId]
    __slots__ = ("armed",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.armed = []
        return self

    def __call__(self, connection_id: ConnectionId) -> None:
        self.armed.append(connection_id)


def _armed(writer: _CallSpy, departure: _CallSpy) -> tuple[HubDisplay, MenuArming]:
    """A store whose shared menu sink is ``departure``, and an arming over it."""
    display = HubDisplay()
    display.lifecycle.present_as(NullDirtyMarker(), departure)
    return display, MenuArming(MenuArmingDeps(display, writer))


def test_admits_an_identified_session_and_arms_its_inbox_and_departure() -> None:
    writer, departure = _CallSpy(), _CallSpy()
    display, arming = _armed(writer, departure)
    conn = ConnectionId("agent")
    display.identify_client(conn, ClientIdentity(kind="mcp-session", name="agent"))

    assert arming.admit(conn) is True
    assert writer.armed == [conn]
    # D2: admitting a menu owner also arms the shared menu sink, so every
    # departure trigger (not only the graceful leg) withdraws the bar.
    display.drop_connection(conn)
    assert departure.armed == [conn]


def test_refuses_an_anonymous_session_and_arms_nothing() -> None:
    writer, departure = _CallSpy(), _CallSpy()
    display, arming = _armed(writer, departure)
    conn = ConnectionId("anon")
    display.register_client(conn)  # registered, but never identified

    assert arming.admit(conn) is False
    display.drop_connection(conn)
    assert writer.armed == []
    assert departure.armed == []


def test_refuses_an_unregistered_session() -> None:
    writer, departure = _CallSpy(), _CallSpy()
    _display, arming = _armed(writer, departure)

    assert arming.admit(ConnectionId("never")) is False
    assert writer.armed == []
    assert departure.armed == []
