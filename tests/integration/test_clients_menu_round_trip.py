"""A Clients menu click, all the way round: Hub → wire → display → Hub.

The unit tests hold each leg on its own. This one runs the whole thing through
production code with nothing stubbed but the ImGui module and the process
boundary: the Hub composes the menu from its live clients, the wire payload the
replicator would send is decoded by the display's own model, a user clicks a leaf
in that model, and the invocation it emits is dispatched Hub-side — to the client
that registered the command, or to the Hub itself for Details.

What it catches that the unit tests cannot: a leaf id the display cannot parse
back, a nesting the decoder drops, or a Details command that routes to a client
instead of being answered.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

import pytest

from punt_lux.display.menus import Submenu
from punt_lux.display.menus.wire import WireMenu
from punt_lux.display.menus.wire_field import WireField
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.details_binding import DetailsBinding
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_interaction_dispatch import HubInteractionDispatch
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.client_details import ClientDetailsOperations
from punt_lux.operations.client_details_port import ClientDetailsPort
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scene_installer import SceneInstaller
from punt_lux.protocol.elements.table import TableElement
from tests.menu_doubles import FakeImGui

if TYPE_CHECKING:
    from punt_lux.protocol import RemoteEventHandlerInvocation

pytestmark = pytest.mark.integration

_BEADS = ConnectionId("beads-session")
_VOXD = ConnectionId("voxd")


@final
class _Leg:
    """A client's listen leg, counting the clicks pushed to it."""

    _woken: int
    __slots__ = ("_woken",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._woken = 0
        return self

    def wake(self) -> None:
        self._woken += 1

    @property
    def woken(self) -> int:
        return self._woken


@final
class _Marks:
    """The dirty marker; the replicator is not what this test drives."""

    def mark_dirty(self, scene_id: SceneId) -> None:
        """A Details install marks its scene for the one sender."""

    def mark_menus(self) -> None:
        """A registration marks the menu for the one sender."""


@final
class _Port:
    """A display port that fails the test if a Hub read reaches around to it."""

    def query(self, method: str, params: object) -> object:
        msg = f"the Hub reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> object:
        msg = f"the Hub reached around to the display: ping({wait!r})"
        raise AssertionError(msg)


@final
class _Wired:
    """A Hub with two live clients, and the display model of the menu it composes."""

    _store: HubDisplay
    _details: ClientDetailsPort
    _router: CallbackRouter
    _legs: dict[ConnectionId, _Leg]
    _sent: list[RemoteEventHandlerInvocation]
    __slots__ = ("_details", "_legs", "_router", "_sent", "_store")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._store = HubDisplay()
        marks = _Marks()
        self._details = ClientDetailsPort(
            ClientDetailsOperations(
                QueryOperations(self._store, Hub(), _Port()),  # type: ignore[arg-type]  # structural port
                SceneInstaller(self._store, marks),
                self._store.clients,
            )
        )
        self._router = CallbackRouter(self._store.clients)
        self._legs = {}
        self._sent = []
        return self

    def connect(self, connection_id: ConnectionId, identity: ClientIdentity) -> None:
        """Bring a client up the way the listen route does, and register a command."""
        leg = _Leg()
        self._legs[connection_id] = leg
        self._store.clients.attach_listener(connection_id, identity, leg)
        command = (
            SessionCallback(id="music", label="Music")
            if connection_id == _VOXD
            else SessionCallback(id="beads", label="Beads")
        )
        self._store.clients.register_callback(connection_id, command, leg)

    def draw(self, *clicks: str) -> FakeImGui:
        """Decode the wire the Hub would send and draw it, clicking what is named.

        The wire goes through the display's own boundary check, so a menu the
        Hub composes but the display would refuse fails here rather than going
        missing from the bar in front of the user.
        """
        imgui = FakeImGui(clicks)
        field = WireField("callback_menus")
        for wire in CallbackMenuReplica(self._store.clients).callback_menu_wire():
            menu = WireMenu.of_payload(wire, field=field)
            Submenu.from_wire(menu, self._sent.append).render(imgui)
        return imgui

    def dispatch_sent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dispatch every emitted click Hub-side, as luxd's socket handler does."""
        binding = DetailsBinding()
        binding.bind(self._details)
        monkeypatch.setattr(
            "punt_lux.domain.hub.details_instance.hub_client_details", binding
        )
        monkeypatch.setattr(
            "punt_lux.domain.hub.replicator_instance.hub_callback_router", self._router
        )
        for invocation in self._sent:
            HubInteractionDispatch.dispatch(invocation)

    def sweep(self, connection_id: ConnectionId) -> None:
        """Drop a client the way the lease sweep does, after the menu was drawn."""
        self._store.clients.discard(connection_id)

    def has_details(self, connection_id: ConnectionId) -> bool:
        """Whether the Hub holds a details scene for this client."""
        return self._scene(connection_id) in self._store.live_scene_ids()

    @staticmethod
    def _scene(connection_id: ConnectionId) -> SceneId:
        return SceneId(f"lux.client-details.{connection_id}")

    def woken(self, connection_id: ConnectionId) -> int:
        return self._legs[connection_id].woken

    def scene_rows(self, connection_id: ConnectionId) -> dict[str, str]:
        """Read back the details table the Hub installed for one client."""
        root = self._store.scene_roots(self._scene(connection_id))[0]
        assert isinstance(root, TableElement)
        return {str(row[0]): str(row[1]) for row in root.rows}


def _wired_with_two_clients() -> _Wired:
    wired = _Wired()
    wired.connect(
        _BEADS,
        ClientIdentity(kind="applet", name="lux · lux · #4b97", repo="/w/lux"),
    )
    wired.connect(_VOXD, ClientIdentity(kind="app", name="voxd"))
    return wired


def test_the_display_draws_what_the_hub_composed() -> None:
    imgui = _wired_with_two_clients().draw()

    assert imgui.labels_under() == ("Clients",)
    assert imgui.labels_under("Clients") == ("lux", "voxd")
    assert imgui.labels_under("Clients", "lux") == ("Beads", "---", "Details")
    assert imgui.labels_under("Clients", "voxd") == ("Music", "---", "Details")


def test_a_command_click_reaches_the_client_that_registered_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wired = _wired_with_two_clients()

    wired.draw("Music")
    wired.dispatch_sent(monkeypatch)

    assert wired.woken(_VOXD) == 1
    assert wired.woken(_BEADS) == 0


def test_a_details_click_is_answered_by_the_hub_with_that_clients_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of Details: what the label stopped saying, said here."""
    wired = _wired_with_two_clients()

    wired.draw("Details")  # both clients' Details lines read the same
    wired.dispatch_sent(monkeypatch)

    assert wired.woken(_VOXD) == 0  # the Hub answered; no client was woken
    assert wired.woken(_BEADS) == 0
    beads = wired.scene_rows(_BEADS)
    assert beads["Client"] == "lux"
    assert beads["Declared name"] == "lux · lux · #4b97"
    assert beads["Kind"] == "applet"
    assert beads["Repository"] == "/w/lux"
    voxd = wired.scene_rows(_VOXD)
    assert voxd["Client"] == "voxd"
    assert voxd["Kind"] == "app"
    assert voxd["Lease"] == "permanent"


def test_two_clients_on_one_repository_are_numbered_all_the_way_to_the_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wired = _Wired()
    for connection in ("first", "second"):
        wired.connect(
            ConnectionId(connection),
            ClientIdentity(kind="mcp-session", name=connection, repo="/w/lux"),
        )

    imgui = wired.draw("Details")
    wired.dispatch_sent(monkeypatch)

    assert imgui.labels_under("Clients") == ("lux", "lux (2)")
    # The frame each Details click opened is titled for the client the menu named.
    assert wired.scene_rows(ConnectionId("first"))["Client"] == "lux"
    assert wired.scene_rows(ConnectionId("second"))["Client"] == "lux (2)"


def test_a_details_scene_installs_no_scene_for_a_client_that_left(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A click can outlive its client; the Hub refuses rather than paint a blank.

    A refusal paints nothing, so the log is the only place it shows. The line
    names the connection, because that is what tells a reader which entry the
    user clicked when the frame they expected never opened.
    """
    wired = _wired_with_two_clients()
    wired.draw("Details")
    wired.sweep(_VOXD)  # its lease lapsed between the paint and the pointer

    with caplog.at_level(logging.INFO):
        wired.dispatch_sent(monkeypatch)

    assert not wired.has_details(_VOXD)
    assert wired.scene_rows(_BEADS)["Client"] == "lux"
    assert f"Details clicked for {_VOXD}" in caplog.text
    assert "no longer holds a session for" in caplog.text
