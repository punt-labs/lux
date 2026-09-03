"""Fakes and builders for the REST surface tests.

Each test drives the real Operations facade over fake collaborators — a fresh
HubDisplay, a recording replicator, a real Hub and registries, and a stub display
port — mounted on a bare FastAPI app through the real RestSurface. This exercises
the whole route → operation → result path without a display process, the same
fake-ports pattern the operations tests use.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations import HubPorts, Operations
from punt_lux.operations.display_reply import DisplayReply
from punt_lux.protocol.messages.observer import ObserverMessage
from punt_lux.rest import RestSurface

# The default identity every fake client declares, so its writes own scenes under
# a named ``cli`` caller; a test passes ``identity={}`` to send none and exercise
# the identity-less rejection (a 401 challenge on a write).
DEFAULT_IDENTITY = {
    "X-Lux-Client-Kind": "cli",
    "X-Lux-Client-Name": "rest-test",
    "X-Lux-Client-Repo": "/w/lux",
}

# The same declaration as a value, for standing the caller up as a listen leg: the
# leg and the identity are one registry write, so attaching needs both.
DEFAULT_IDENTITY_MODEL = ClientIdentity(kind="cli", name="rest-test", repo="/w/lux")

# The connection the default identity resolves to on every transport. A test that
# needs the caller push-reachable — registering a menu callback requires a live
# listen leg — registers a listener for this connection via ``listening=True``.
DEFAULT_CONNECTION = connection_for(
    {"kind": "cli", "name": "rest-test", "repo": "/w/lux"}
)


class SilentListener:
    """A CallbackListener whose wake does nothing — presence is what is tested."""

    def wake(self) -> None:
        """Stand in for a live leg's drain; these tests assert the gate."""


class Recorder:
    """A DirtyMarker that records the replicator signals an operation sends."""

    def __init__(self) -> None:
        self.dirtied: list[SceneId] = []
        self.menus = 0

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.dirtied.append(scene_id)

    def mark_menus(self) -> None:
        self.menus += 1


class ForbiddenPort:
    """A DisplayPort that fails the test if any proxied call is made."""

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        raise AssertionError(f"unexpected display proxy: query({method!r})")

    def ping(self, wait: float | None) -> DisplayReply:
        raise AssertionError(f"unexpected display proxy: ping({wait!r})")


class ForbiddenInbox:
    """Inbox port helpers that fail the test if pub-sub is ever reached.

    REST exposes no pub-sub routes, so ``ensure_writer``/``next_event`` must
    never fire through these fakes. Wiring the process-singleton inbox here
    would smuggle global state into an otherwise-isolated fixture; failing loud
    surfaces an unexpected call instead (the ForbiddenPort philosophy).
    """

    def ensure_writer(self, connection_id: ConnectionId) -> None:
        raise AssertionError(f"unexpected pub-sub: ensure_writer({connection_id!r})")

    def next_event(
        self, connection_id: ConnectionId, timeout: float
    ) -> ObserverMessage | None:
        raise AssertionError(f"unexpected pub-sub: next_event({connection_id!r})")


class StubPort:
    """A DisplayPort returning one preset reply and recording the ping wait."""

    def __init__(self, reply: DisplayReply) -> None:
        self._reply = reply
        self.ping_wait: float | None = None

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        return self._reply

    def ping(self, wait: float | None) -> DisplayReply:
        self.ping_wait = wait
        return self._reply


def make_facade(
    *,
    display_port: object,
    store: HubDisplay | None = None,
    router: CallbackRouter | None = None,
) -> Operations:
    """Build the real facade over fresh domain objects and the given port.

    ``store`` lets a caller hold the ``HubDisplay`` to inspect what an operation
    installed; a fresh one is made when it is not supplied. ``router`` lets a
    caller pre-register a listener so the callback routes see a push-reachable
    connection.
    """
    inbox = ForbiddenInbox()
    display = store if store is not None else HubDisplay()
    return Operations.for_store(
        display,
        Recorder(),
        hub=Hub(),
        menu_registry=HubMenuRegistry(),
        callback_router=router or CallbackRouter(display.clients),
        ports=HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=inbox.ensure_writer,
            next_event=inbox.next_event,
            display_port=display_port,  # type: ignore[arg-type]  # DisplayPort protocol; fakes satisfy it structurally
        ),
    )


def make_client(
    *,
    display_port: object | None = None,
    store: HubDisplay | None = None,
    identity: Mapping[str, str] | None = None,
    listening: bool = False,
) -> TestClient:
    """Mount the real REST surface over a fake-backed facade on a bare app.

    Pass ``store`` to hold the ``HubDisplay`` the routes install into. The client
    declares :data:`DEFAULT_IDENTITY` on every request unless ``identity`` overrides
    it; pass ``identity={}`` to send no identity headers (a write is then rejected).
    Pass ``listening=True`` to stand the caller up as a client that also holds a
    listen leg, which registering a menu callback requires.
    """
    port = display_port if display_port is not None else ForbiddenPort()
    app = FastAPI()
    display = store if store is not None else HubDisplay()
    router = CallbackRouter(display.clients)
    if listening:
        display.clients.attach_listener(
            DEFAULT_CONNECTION, DEFAULT_IDENTITY_MODEL, SilentListener()
        )
    facade = make_facade(display_port=port, store=display, router=router)
    RestSurface(facade).mount(app)
    headers = dict(DEFAULT_IDENTITY if identity is None else identity)
    return TestClient(app, headers=headers)
