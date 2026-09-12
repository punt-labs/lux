"""MenuEventRouter — deliver an agent menu click to the owning session's inbox.

The router reuses the live-session read (gating the enqueue like CallbackRouter)
and a non-resurrecting sink: a click for a live session with an inbox is
delivered as a reserved ``lux.menu`` event; a click for a session gone from the
live set, or one whose inbox is absent, is ``provider_gone``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.hub.menu_event import MENU_TOPIC, MenuEventRouter, MenuSelection
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.protocol.messages.observer import ObserverMessage


@final
class _Live:
    """A LiveSessions fake reporting a fixed set of live connections."""

    _live: frozenset[ConnectionId]
    __slots__ = ("_live",)

    def __new__(cls, *live: ConnectionId) -> Self:
        self = super().__new__(cls)
        self._live = frozenset(live)
        return self

    def live_sessions(self) -> Mapping[ConnectionId, ClientSession]:
        return {c: cast("ClientSession", object()) for c in self._live}


@final
class _Sink:
    """A menu-event sink recording puts; ``present`` decides if an inbox exists."""

    present: bool
    puts: list[tuple[ConnectionId, ObserverMessage]]
    __slots__ = ("present", "puts")

    def __new__(cls, present: bool) -> Self:
        self = super().__new__(cls)
        self.present = present
        self.puts = []
        return self

    def __call__(self, connection_id: ConnectionId, message: ObserverMessage) -> bool:
        self.puts.append((connection_id, message))
        return self.present


def test_selection_reads_the_item_id_and_menu_label() -> None:
    selection = MenuSelection.of("run_btn", {"menu": "Tools", "item": "Run"})
    assert selection == MenuSelection(menu="Tools", item="run_btn")


def test_selection_tolerates_a_valueless_click() -> None:
    assert MenuSelection.of("run_btn", None) == MenuSelection(menu="", item="run_btn")


def test_selection_renders_the_reserved_lux_menu_event() -> None:
    message = MenuSelection(menu="Tools", item="run_btn").observer_message()
    assert message.topic == MENU_TOPIC
    assert dict(message.payload) == {"menu": "Tools", "item": "run_btn"}


def test_deliver_lands_the_event_on_a_live_session_with_an_inbox() -> None:
    conn = ConnectionId("live")
    sink = _Sink(present=True)
    router = MenuEventRouter(_Live(conn), sink)

    outcome = router.deliver(conn, MenuSelection(menu="Tools", item="run_btn"))

    assert outcome == "delivered"
    assert [(c, m.topic) for c, m in sink.puts] == [(conn, MENU_TOPIC)]


def test_deliver_refuses_a_session_gone_from_the_live_set() -> None:
    conn = ConnectionId("gone")
    sink = _Sink(present=True)
    router = MenuEventRouter(_Live(), sink)  # no live sessions

    outcome = router.deliver(conn, MenuSelection(menu="", item="run_btn"))

    assert outcome == "provider_gone"
    assert sink.puts == []  # the live gate refuses before the sink


def test_deliver_refuses_a_live_session_with_no_inbox() -> None:
    # A listener-only session (applet), or one that departed after the read, has
    # no inbox queue; the non-resurrecting sink returns False and nothing lands.
    conn = ConnectionId("no-inbox")
    sink = _Sink(present=False)
    router = MenuEventRouter(_Live(conn), sink)

    outcome = router.deliver(conn, MenuSelection(menu="", item="run_btn"))

    assert outcome == "provider_gone"
