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
from punt_lux.operations import HubPorts, Operations, Scope
from punt_lux.operations.display_reply import DisplayReply
from punt_lux.protocol.messages.observer import ObserverMessage
from punt_lux.rest import RestSurface

_TEST_SCOPE = Scope(ConnectionId("rest-test"))


class Recorder:
    """A DirtyMarker that records the replicator signals an operation sends."""

    def __init__(self) -> None:
        self.dirtied: list[SceneId] = []
        self.cleared = 0
        self.menus = 0

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.dirtied.append(scene_id)

    def mark_cleared(self) -> None:
        self.cleared += 1

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


def make_facade(*, display_port: object) -> Operations:
    """Build the real facade over fresh domain objects and the given port."""
    inbox = ForbiddenInbox()
    return Operations.for_store(
        HubDisplay(),
        Recorder(),
        hub=Hub(),
        client_registry=ClientRegistry(),
        menu_registry=HubMenuRegistry(),
        ports=HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=inbox.ensure_writer,
            next_event=inbox.next_event,
        ),
        display_port=display_port,  # type: ignore[arg-type]  # DisplayPort protocol; fakes satisfy it structurally
    )


def make_client(*, display_port: object | None = None) -> TestClient:
    """Mount the real REST surface over a fake-backed facade on a bare app."""
    port = display_port if display_port is not None else ForbiddenPort()
    app = FastAPI()
    RestSurface(make_facade(display_port=port), scope=_TEST_SCOPE).mount(app)
    return TestClient(app)
