"""The vox Music Player acceptance scenario — the named end-to-end proof.

voxd is a persistent app client (kind=app, name=voxd, lease 30) that registers a
'Music' menu callback and subscribes to its own music topics. This composes the
two v1 loops the menu epic ships, end to end over the production WebSocket listen
leg:

1. voxd registers 'Music'; the Hub menu build shows one submenu "voxd"
   with a "Music" leaf; a leaf click routes back to voxd's live WebSocket
   connection as a callback frame.
2. an in-scene Play-row button carries the typed publish attribute; firing it
   publishes ``music.play {album_id}`` to voxd, which receives it as an event
   frame on the same connection.

Both legs drive the production :class:`HubListenTransport` over Starlette's
``TestClient`` with fresh domain objects, so no display process and no uvicorn
thread is involved. What a real display would add is the GLFW pixel hit-test that
turns a click into the invocation; the Hub-side invoke stands in for exactly that
step, and the leaf id and the button event it carries are byte-identical to what
the display would send. The publish sink is :class:`HubPublishSink`'s own shape —
a connection-scoped adapter onto ``Hub.publish`` — bound to this test's Hub so the
button's declared topic reaches the very subscriber the WebSocket registered.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Self, final

from fastapi import FastAPI
from fastapi.testclient import TestClient

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.callback_menu import CallbackMenu
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import ClientId, ElementId, SceneId, Topic
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.operations.callbacks import CallbackOperations
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import Ok
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.ws_transport import HubListenTransport

# voxd's identity and the connection id both legs share — the WebSocket handshake
# declares the same X-Lux-Client-* headers REST uses, so the callback registered
# under this identity routes to the connection the WebSocket bound.
_HEADERS = {
    "X-Lux-Client-Kind": "app",
    "X-Lux-Client-Name": "voxd",
}
# What voxd actually declares (punt_vox/voxd/music_player/lux_clients.py): an
# app, named for itself, working in no repository — a daemon belongs to the
# machine, not to a checkout, which is also why the menu calls it ``voxd``.
_IDENTITY = ClientIdentity(kind="app", name="voxd")
_CONN = connection_for({"kind": "app", "name": "voxd"})


@final
class _Replicator:
    """A ``DirtyMarker`` stub recording the flags the operations raise."""

    _marks: list[str]
    __slots__ = ("_marks",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._marks = []
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self._marks.append(f"dirty:{scene_id}")

    def mark_menus(self) -> None:
        self._marks.append("menus")


@final
class _HubSink:
    """A connection-scoped publish sink onto the test's Hub — HubPublishSink's shape.

    A Play-row button's publish decorator fires this on click; it forwards the
    declared topic and payload to ``Hub.publish`` against voxd's connection, the
    exact adapter luxd binds when it decodes a button into HubDisplay.
    """

    _hub: Hub
    __slots__ = ("_hub",)

    def __new__(cls, hub: Hub) -> Self:
        self = super().__new__(cls)
        self._hub = hub
        return self

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        self._hub.publish(_CONN, Topic(topic), payload)


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
    """Mount the production listen transport over fresh domain objects."""
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


def _play_button(hub: Hub, album_id: str) -> ButtonElement:
    """Decode a Play-row button carrying a ``music.play {album_id}`` publish.

    Decoded through a Hub-bound factory whose publish sink is the connection-scoped
    adapter onto ``Hub.publish`` — the same wiring luxd applies to a button that
    lands in HubDisplay, so a fire fans the declared topic to voxd's subscribers.
    """
    factory = JsonElementFactory(
        renderer_factory=RaisingRendererFactory(),
        emit=lambda _msg: None,
        publish_sink=_HubSink(hub),
    )
    button = factory.decode(
        {
            "kind": "button",
            "id": "play",
            "label": "Play",
            "publish": {"topic": "music.play", "payload": {"album_id": album_id}},
        }
    )
    assert isinstance(button, ButtonElement)
    return button


@final
class _SilentLeg:
    """A listen leg stand-in for the cases that build a menu without a socket."""

    def wake(self) -> None:
        """Delivery is the websocket's job in the click test below."""


def test_the_music_build_shows_one_voxd_submenu_with_a_music_leaf() -> None:
    _client, _hub, clients, _router = _wired()
    # voxd connects: identity and listen leg in one write, as the /ws route does.
    leg = _SilentLeg()
    clients.attach_listener(_CONN, _IDENTITY, leg)
    outcome = clients.register_callback(
        _CONN, SessionCallback(id="music", label="Music"), leg
    )
    assert outcome == "registered"

    menus = CallbackMenu.from_named(clients.named_sessions())

    # voxd is a client like any other: one submenu under Clients, named for
    # itself because a daemon works in no repository, with the Music leaf whose
    # id round-trips a click back to voxd's connection.
    assert [menu.label for menu in menus] == ["Clients"]
    voxd = menus[0].items[0]
    assert isinstance(voxd, Menu)
    assert voxd.label == "voxd"
    leaf = voxd.items[0]
    assert isinstance(leaf, MenuAction)
    assert leaf.label == "Music"
    assert leaf.id == CallbackInvocation(_CONN, "music").menu_id


def test_a_music_leaf_click_reaches_voxds_live_websocket() -> None:
    client, _hub, clients, router = _wired()
    callbacks = CallbackOperations(clients, router, _Replicator())
    leaf_id = CallbackInvocation(_CONN, "music").menu_id

    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        ws.receive_json()  # ready — voxd's leg is installed by now
        # Registration happens from the live connection, which is what an app's
        # on_connect hook does: a leg taking the slot clears what the last one
        # owned, so entries registered before connecting would not survive it.
        leg = clients.listener_of(_CONN)
        assert leg is not None
        registration = clients.register_callback(
            _CONN, SessionCallback(id="music", label="Music"), leg
        )
        assert registration == "registered"
        # The display-less stand-in for a leaf click: the invoke a menu-leaf click
        # dispatches, driven with the exact id the built leaf carries.
        outcome = callbacks.invoke_callback(leaf_id)
        assert isinstance(outcome, Ok)
        assert ws.receive_json() == {"kind": "callback", "callback_id": "music"}


def test_a_stale_leaf_click_after_the_session_is_gone_fails_gracefully() -> None:
    _client, _hub, clients, router = _wired()
    callbacks = CallbackOperations(clients, router, _Replicator())
    # No session was ever recorded for _CONN, so its leaf id resolves to nobody.
    outcome = callbacks.invoke_callback(CallbackInvocation(_CONN, "music").menu_id)
    assert isinstance(outcome, OpError)
    assert outcome.code == "not_found"


def test_a_play_row_publish_button_reaches_voxds_music_subscriber() -> None:
    client, hub, _clients, _router = _wired()
    with client.websocket_connect("/ws", headers=_HEADERS) as ws:
        ws.receive_json()  # ready
        ws.send_json({"kind": "subscribe", "topics": ["music.play"]})
        _eventually(lambda: Topic("music.play") in hub.topics_for(_CONN))

        # A user clicks the Play row: the button fires, its publish decorator fans
        # music.play {album_id} to voxd, which is subscribed on this connection.
        button = _play_button(hub, album_id="jazz-1")
        button.fire(
            ButtonClicked(
                scene_id=SceneId("player"),
                element_id=ElementId("play"),
                owner_id=ClientId(str(_CONN)),
            )
        )

        assert ws.receive_json() == {
            "kind": "event",
            "topic": "music.play",
            "payload": {"album_id": "jazz-1"},
        }
