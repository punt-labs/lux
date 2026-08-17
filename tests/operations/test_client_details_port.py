"""ClientDetailsPort — the Details command as the Hub's dispatch sees it.

The dispatch hands over a connection id and gets back an outcome that reports
itself. It cannot name an ``OpError``, so the port is where the operation's
typed result becomes one of the two outcomes.

The same class carries the wiring recipe both composition roots call, so a click
answers out of one store whichever root bound the renderer last.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.details_outcome import DetailsRefused, DetailsShown
from punt_lux.domain.hub.details_renderer import ClientDetailsRenderer
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.client_details_port import ClientDetailsPort
from punt_lux.operations.ports import HubPorts

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort


class _Marks:
    """A DirtyMarker recording the scenes an install marked for the replicator."""

    _marked: list[str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._marked = []
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self._marked.append(str(scene_id))

    def mark_menus(self) -> None:
        """The menu is not what a Details click changes."""

    @property
    def marked(self) -> list[str]:
        return self._marked


class _ForbiddenPort:
    """A DisplayPort that fails the test if the read reaches around to it."""

    def query(self, method: str, params: object) -> object:
        msg = f"Details reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> object:
        msg = f"Details reached around to the display: ping({wait!r})"
        raise AssertionError(msg)


def _ports() -> HubPorts:
    """The collaborators a composition root hands the recipe, with no display."""
    return HubPorts(
        element_factory=hub_element_factory,
        ensure_writer=lambda _connection: None,
        next_event=lambda _connection, _timeout: None,
        display_port=cast("DisplayPort", _ForbiddenPort()),
    )


def _wired(store: HubDisplay, hub: Hub) -> tuple[ClientDetailsPort, _Marks]:
    """Build the port the way a composition root does."""
    marks = _Marks()
    return ClientDetailsPort.for_store(store, marks, hub=hub, ports=_ports()), marks


def _named(store: HubDisplay, connection: str) -> ConnectionId:
    """Record a client and take the read that names it, as the menu build does."""
    conn = ConnectionId(connection)
    identity = ClientIdentity(
        kind="applet", name="lux · lux · #4b97 · lux-beads", repo="/w/lux"
    )
    store.identify_client(conn, identity)
    store.clients.named_sessions()
    return conn


class TestWhatTheDispatchGetsBack:
    """Shown, or nothing to show — and never an operations result type."""

    def test_a_live_client_is_shown(self) -> None:
        store, hub = HubDisplay(), Hub()
        port, _marks = _wired(store, hub)

        assert port.render_details(_named(store, "c1")) == DetailsShown()

    def test_a_client_the_hub_no_longer_holds_is_refused(self) -> None:
        store, hub = HubDisplay(), Hub()
        port, _marks = _wired(store, hub)
        gone = ConnectionId("gone")

        assert port.render_details(gone) == DetailsRefused(gone)

    def test_a_refusal_installs_no_scene(self) -> None:
        store, hub = HubDisplay(), Hub()
        port, marks = _wired(store, hub)

        port.render_details(ConnectionId("gone"))

        assert marks.marked == []
        assert list(store.live_scene_ids()) == []

    def test_the_port_satisfies_the_contract_the_dispatch_binds(self) -> None:
        store, hub = HubDisplay(), Hub()
        port, _marks = _wired(store, hub)

        assert isinstance(port, ClientDetailsRenderer)


class TestHowACompositionRootBuildsIt:
    """One recipe, called by both roots — two doors onto one Hub."""

    def test_the_recipe_wires_a_working_command_over_the_store(self) -> None:
        store, hub = HubDisplay(), Hub()
        conn = _named(store, "c1")
        port, marks = _wired(store, hub)

        assert port.render_details(conn) == DetailsShown()
        composed = ConnectionScopedId.compose(conn, f"lux.client-details.{conn}")
        assert marks.marked == [composed]

    def test_either_root_shows_into_the_same_scene(self) -> None:
        store, hub = HubDisplay(), Hub()
        conn = _named(store, "c1")
        mcp, _mcp_marks = _wired(store, hub)
        rest, _rest_marks = _wired(store, hub)

        assert mcp.render_details(conn) == DetailsShown()
        assert rest.render_details(conn) == DetailsShown()
        composed = ConnectionScopedId.compose(conn, f"lux.client-details.{conn}")
        assert list(store.live_scene_ids()) == [SceneId(composed)]
