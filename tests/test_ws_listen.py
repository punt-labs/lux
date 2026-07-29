"""The persistent WebSocket listen leg — handshake, callback push, event push.

Drives the real :class:`HubListenTransport` over fresh domain objects through
Starlette's ``TestClient``. The handshake declares identity in the same
``X-Lux-Client-*`` headers REST uses, so a callback registered under that identity
is routed to the very connection the WebSocket bound — the two legs' shared id.
"""

from __future__ import annotations

import time
from collections.abc import Callable

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
from punt_lux.domain.ids import Topic
from punt_lux.ws_listen import HubListenTransport

_HEADERS = {
    "X-Lux-Client-Kind": "app",
    "X-Lux-Client-Name": "voxd",
    "X-Lux-Client-Repo": "/w/vox",
}
_CONN = connection_for({"kind": "app", "name": "voxd", "repo": "/w/vox"})


def _wired() -> tuple[TestClient, Hub, HubClientRegistry, CallbackRouter]:
    hub, clients = Hub(), HubClientRegistry()
    router = CallbackRouter(clients)
    app = FastAPI()
    HubListenTransport(hub, clients, router).mount(app)
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
