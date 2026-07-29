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

from punt_lux.domain.hub.clients import ClientRegistry
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
# a named ``cli`` caller; a test omits it (``identity=None``) to exercise the
# anonymous path and the identification challenge.
DEFAULT_IDENTITY = {
    "X-Lux-Client-Kind": "cli",
    "X-Lux-Client-Name": "rest-test",
    "X-Lux-Client-Repo": "/w/lux",
}


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


def make_facade(*, display_port: object, store: HubDisplay | None = None) -> Operations:
    """Build the real facade over fresh domain objects and the given port.

    ``store`` lets a caller hold the ``HubDisplay`` to inspect what an operation
    installed; a fresh one is made when it is not supplied.
    """
    inbox = ForbiddenInbox()
    return Operations.for_store(
        store if store is not None else HubDisplay(),
        Recorder(),
        hub=Hub(),
        client_registry=ClientRegistry(),
        menu_registry=HubMenuRegistry(),
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
) -> TestClient:
    """Mount the real REST surface over a fake-backed facade on a bare app.

    Pass ``store`` to hold the ``HubDisplay`` the routes install into. The client
    declares :data:`DEFAULT_IDENTITY` on every request unless ``identity`` overrides
    it; pass ``identity={}`` to send no identity headers (the anonymous path).
    """
    port = display_port if display_port is not None else ForbiddenPort()
    app = FastAPI()
    facade = make_facade(display_port=port, store=store)
    RestSurface(facade).mount(app)
    headers = dict(DEFAULT_IDENTITY if identity is None else identity)
    return TestClient(app, headers=headers)
