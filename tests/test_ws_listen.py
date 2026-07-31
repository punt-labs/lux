"""The persistent WebSocket listen leg — handshake, callback push, event push.

Drives the real :class:`HubListenTransport` over fresh domain objects through
Starlette's ``TestClient``. The handshake declares identity in the same
``X-Lux-Client-*`` headers REST uses, so a callback registered under that identity
is routed to the very connection the WebSocket bound — the two legs' shared id.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
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
from punt_lux.ws_listen import HubListenSession, HubListenTransport

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
        ws.receive_json()  # ready — the listener is registered by now
        clients.register_callback(_CONN, SessionCallback(id="beads", label="Beads"))
        assert router.route(CallbackInvocation(_CONN, "beads")) == "routed"
        assert ws.receive_json() == {"kind": "callback", "callback_id": "beads"}


def test_a_click_buffered_before_connect_is_drained_on_connect() -> None:
    client, _hub, clients, router = _wired()
    # The session must exist for the click to route, so identify and register it,
    # then route while nothing is connected — the hold buffers the click.
    clients.record(_CONN, ClientIdentity(kind="app", name="voxd", repo="/w/vox"))
    clients.register_callback(_CONN, SessionCallback(id="beads", label="Beads"))
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
        ws.receive_json()  # ready — the leg is up and its listener registered
        clients.register_callback(_CONN, SessionCallback(id="beads", label="Beads"))
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
