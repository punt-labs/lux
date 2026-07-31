"""The persistent WebSocket listen leg — handshake, callback push, event push.

Drives the real :class:`HubListenTransport` over fresh domain objects through
Starlette's ``TestClient``. The handshake declares identity in the same
``X-Lux-Client-*`` headers REST uses, so a callback registered under that identity
is routed to the very connection the WebSocket bound — the two legs' shared id.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import time
from collections.abc import Callable
from pathlib import Path
from typing import Self, final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import SceneId, Topic
from punt_lux.protocol.messages.listen import CallbackFrame
from punt_lux.ws_listen import HubListenSession
from punt_lux.ws_transport import HubListenTransport

_HEADERS = {
    "X-Lux-Client-Kind": "app",
    "X-Lux-Client-Name": "voxd",
    "X-Lux-Client-Repo": "/w/vox",
}
_CONN = connection_for({"kind": "app", "name": "voxd", "repo": "/w/vox"})


@final
class _MenuFlag:
    """A DirtyMarker recording the menu re-pushes a teardown triggers."""

    _menus: int
    __slots__ = ("_menus",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._menus = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError("the listen leg must never mark a scene dirty")

    def mark_menus(self) -> None:
        self._menus += 1

    @property
    def pushes(self) -> int:
        return self._menus


def _wired() -> tuple[TestClient, Hub, HubClientRegistry, CallbackRouter]:
    hub, clients = Hub(), HubClientRegistry()
    router = CallbackRouter(clients)
    app = FastAPI()
    HubListenTransport(hub, clients, router, _MenuFlag()).mount(app)
    return TestClient(app), hub, clients, router


def _eventually(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    """Spin until ``predicate`` holds — the read loop applies frames off-thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached within timeout")


_IDENTITY = ClientIdentity(kind="app", name="voxd", repo="/w/vox")


@final
class _SilentLeg:
    """A leg that holds the slot and never delivers — a socket mid-teardown."""

    def wake(self) -> None:
        """Deliberately silent: the click stays in the hold for the next connect."""


def _register(clients: HubClientRegistry, callback_id: str) -> None:
    """Register a callback the way a connected app does — against its own leg."""
    leg = clients.listener_of(_CONN)
    assert leg is not None, "the session must hold a listen leg to own a callback"
    outcome = clients.register_callback(
        _CONN, SessionCallback(id=callback_id, label="Beads"), leg
    )
    assert outcome == "registered"


def test_the_handshake_readies_the_shared_connection_id() -> None:
    client, *_ = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        assert ws.receive_json() == {"kind": "ready", "connection_id": str(_CONN)}


def test_an_unidentified_handshake_is_refused() -> None:
    client, *_ = _wired()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws") as ws:
        ws.receive_json()


def test_a_routed_click_is_pushed_to_the_live_connection() -> None:
    client, _hub, clients, router = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        ws.receive_json()  # ready — the leg holds the connection's slot by now
        _register(clients, "beads")
        assert router.route(CallbackInvocation(_CONN, "beads")) == "routed"
        assert ws.receive_json() == {"kind": "callback", "callback_id": "beads"}


def test_a_click_buffered_before_connect_is_drained_on_connect() -> None:
    """The hold outlives the leg, so a click nobody delivered survives the gap.

    A callback dies with the listener that registered it, but the hold does not:
    a click already routed when the socket goes is buffered, and the next
    connection of the same identity drains it before anything new is routed. The
    quiet leg here is a listener that took the slot and never delivers, which is
    what a socket in mid-teardown amounts to.
    """
    client, _hub, clients, router = _wired()
    quiet = _SilentLeg()
    clients.attach_listener(_CONN, _IDENTITY, quiet)
    outcome = clients.register_callback(
        _CONN, SessionCallback(id="beads", label="Beads"), quiet
    )
    assert outcome == "registered"
    assert router.route(CallbackInvocation(_CONN, "beads")) == "routed"

    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        ws.receive_json()  # ready
        # The buffered click drains on connect, before any new route.
        assert ws.receive_json() == {"kind": "callback", "callback_id": "beads"}


def test_a_departed_connections_menu_items_leave_with_it() -> None:
    """No ghost entries: an item whose owner is gone must not stay clickable.

    A callback outliving its listener is an entry the user can click into
    silence — the click routes "Ok", lands in a hold, and nothing ever drains
    it. The session itself survives, because the same identity reconnecting
    re-registers from ``on_connect``; only the callbacks go.
    """
    client, _hub, clients, _router = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        ws.receive_json()  # ready — the leg is up and holds the connection's slot
        _register(clients, "beads")
        session = clients.session_of(_CONN)
        assert session is not None
        assert session.owns_callback("beads")

    _eventually(lambda: not _owns(clients, "beads"))
    survivor = clients.session_of(_CONN)
    assert survivor is not None  # the session stays; a reconnect re-registers
    assert survivor.identity is not None


def _owns(clients: HubClientRegistry, callback_id: str) -> bool:
    session = clients.session_of(_CONN)
    return session is not None and session.owns_callback(callback_id)


def test_a_subscribed_topics_publish_is_pushed() -> None:
    client, hub, _clients, _router = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        ws.receive_json()  # ready
        ws.send_json({"kind": "subscribe", "topics": ["music.play"]})
        _eventually(lambda: Topic("music.play") in hub.topics_for(_CONN))
        hub.publish(_CONN, Topic("music.play"), {"album_id": "jazz-1"})
        assert ws.receive_json() == {
            "kind": "event",
            "topic": "music.play",
            "payload": {"album_id": "jazz-1"},
        }


def test_a_non_json_frame_closes_the_connection_as_a_protocol_error() -> None:
    client, *_ = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        ws.receive_json()  # ready
        ws.send_text("this is not a frame")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1002  # protocol error, not a 1011 server fault


def test_an_unknown_frame_kind_closes_the_connection_as_a_protocol_error() -> None:
    client, *_ = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        ws.receive_json()  # ready
        ws.send_json({"kind": "teleport"})  # not a defined client frame
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1002


@final
class _GoneWebSocket:
    """A WebSocket whose send raises, standing in for a peer that has gone away."""

    def __init__(self, send_error: Exception) -> None:
        self._send_error = send_error

    async def accept(self) -> None:
        """Accepting succeeds; the peer is only discovered gone on the first write."""

    async def send_text(self, _text: str) -> None:
        raise self._send_error


def _session_over(send_error: Exception) -> HubListenSession:
    hub, clients = Hub(), HubClientRegistry()
    return HubListenSession(
        _GoneWebSocket(send_error),  # type: ignore[arg-type]  # structural fake for the write path
        _CONN,
        ClientIdentity(kind="app", name="voxd", repo="/w/vox"),
        hub,
        clients,
        CallbackRouter(clients),
        _MenuFlag(),
    )


def test_the_write_loop_ends_cleanly_when_the_peer_disconnected() -> None:
    # A send to a peer already going away raises WebSocketDisconnect; a normal
    # disconnect must not become a server error out of run().
    async def scenario() -> None:
        session = _session_over(WebSocketDisconnect(code=1006))
        session._outbound.put_nowait(CallbackFrame(callback_id="beads"))
        await session._write_loop()  # returns rather than propagating

    asyncio.run(scenario())


def test_the_write_loop_ends_cleanly_on_a_send_after_close() -> None:
    # Once starlette has seen the close, send raises RuntimeError; that too is
    # peer-gone, not a fault, so the loop ends cleanly.
    async def scenario() -> None:
        session = _session_over(RuntimeError("Cannot call send once closed"))
        session._outbound.put_nowait(CallbackFrame(callback_id="beads"))
        await session._write_loop()

    asyncio.run(scenario())


def test_a_peer_that_dies_before_the_handshake_leaves_no_listener() -> None:
    """The gate's own invariant: no listener outlives the connection that made it.

    A client can go away between the accept and the handshake write, by which
    point the listener is registered. If that failure escaped the teardown, the
    Hub would hold a listener for a connection nothing can reach — and would then
    admit a menu callback from that identity, since holding a listener is exactly
    what the registration gate checks for.
    """
    hub, clients = Hub(), HubClientRegistry()
    router = CallbackRouter(clients)

    async def _drive() -> None:
        # The session binds the running loop at construction, so it is built here.
        session = HubListenSession(
            _GoneWebSocket(WebSocketDisconnect(code=1006)),  # type: ignore[arg-type]  # structural fake
            _CONN,
            ClientIdentity(kind="app", name="voxd", repo="/w/vox"),
            hub,
            clients,
            router,
            _MenuFlag(),
        )
        await session.run()

    with pytest.raises(WebSocketDisconnect):
        asyncio.run(_drive())

    session = clients.session_of(_CONN)
    assert session is not None
    assert not session.is_push_reachable  # nothing is left holding the gate open


def test_a_second_live_session_of_one_identity_takes_the_connection() -> None:
    """Two sessions of one identity share a connection, and the newest owns it.

    The id is derived from the identity, so a second process — or a reconnect
    that beats its predecessor's teardown — lands on the same slot. Whoever
    connected last is the one a click must reach.
    """
    client, _hub, clients, _router = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as first:
        first.receive_json()  # ready
        first_leg = clients.listener_of(_CONN)
        with client.websocket_connect("/ws", headers=_HEADERS) as second:
            second.receive_json()  # ready
            second_leg = clients.listener_of(_CONN)

            assert second_leg is not None
            assert second_leg is not first_leg


def test_a_new_leg_arrives_with_none_of_its_predecessors_menu_entries() -> None:
    """Reachable with no interleaving at all — just a connect while one is live.

    Left in place, the predecessor's entries stay in the bar with every click
    routed to the newcomer, and nothing would ever withdraw them: the session
    that could has lost the slot.
    """
    client, _hub, clients, _router = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as first:
        first.receive_json()  # ready
        _register(clients, "beads")
        assert _owns(clients, "beads")

        with client.websocket_connect("/ws", headers=_HEADERS) as second:
            second.receive_json()  # ready
            assert not _owns(clients, "beads")


def test_a_superseded_sessions_teardown_leaves_its_successor_whole() -> None:
    """The stale teardown: the defect this whole design exists to rule out.

    The predecessor departs *after* the successor has taken the slot — the order
    a reconnect after a backoff produces, with the predecessor still suspended
    awaiting its cancelled writer. Unguarded, its teardown removes the
    successor's leg and callbacks, and nothing repairs that: the successor keeps
    renewing its lease, so no sweep ever reaches it, and it goes on believing it
    is push-reachable while owning nothing.
    """
    client, _hub, clients, router = _wired()
    predecessor = contextlib.ExitStack()
    first = predecessor.enter_context(client.websocket_connect("/ws", headers=_HEADERS))
    first.receive_json()  # ready

    with client.websocket_connect("/ws", headers=_HEADERS) as second:
        second.receive_json()  # ready
        successor = clients.listener_of(_CONN)
        _register(clients, "beads")

        # It departs while the successor is live and pumping. Closing the client
        # side joins the server task, so its teardown has run by the time this
        # returns — removing the ownership guard makes the asserts below fail.
        predecessor.close()

        assert clients.listener_of(_CONN) is successor  # the slot was not taken
        assert _owns(clients, "beads")  # nor were its entries
        # And it is still reachable: a click routes and lands on its socket.
        assert router.route(CallbackInvocation(_CONN, "beads")) == "routed"
        assert second.receive_json() == {"kind": "callback", "callback_id": "beads"}


def test_only_an_owned_teardown_runs_the_disconnect_cascade() -> None:
    """A stale teardown must not drop the successor's subscriptions or writer.

    The cascade unbinds the connection's writer and its subscriptions, which by
    the time a superseded session resumes belong to the session that replaced it.
    Running it from a session that removed nothing would silence a live leg.
    """
    client, hub, _clients, _router = _wired()
    predecessor = contextlib.ExitStack()
    first = predecessor.enter_context(client.websocket_connect("/ws", headers=_HEADERS))
    first.receive_json()  # ready

    with client.websocket_connect("/ws", headers=_HEADERS) as second:
        second.receive_json()  # ready
        second.send_json({"kind": "subscribe", "topics": ["music.play"]})
        _eventually(lambda: Topic("music.play") in hub.topics_for(_CONN))

        predecessor.close()  # its teardown runs before this returns

        assert Topic("music.play") in hub.topics_for(_CONN)  # the cascade stayed away
        hub.publish(_CONN, Topic("music.play"), {"album_id": "jazz-1"})
        assert second.receive_json() == {
            "kind": "event",
            "topic": "music.play",
            "payload": {"album_id": "jazz-1"},
        }


def test_the_teardown_contains_no_await() -> None:
    """The condition the unguarded writer removal rests on, checked structurally.

    The disconnect cascade drops the connection's writer without comparing it to
    anything, and that is sound only because nothing can interleave between the
    release that authorised it and the cascade itself. On a single event loop
    that holds exactly as long as the teardown has no suspension point. An
    ``await`` added here would reopen the window and quietly invalidate the model
    this design was verified against, so it is caught at the source rather than
    waited for in production.
    """
    source = Path(inspect.getsourcefile(HubListenSession) or "").read_text()
    teardown = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == "_teardown"
    )
    suspensions = [
        node
        for node in ast.walk(teardown)
        if isinstance(node, ast.Await | ast.AsyncWith | ast.AsyncFor)
    ]
    assert suspensions == [], "_teardown must stay await-free; see its docstring"
