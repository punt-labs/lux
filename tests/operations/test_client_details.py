"""ClientDetailsOperations — the Hub's own answer to a Details click.

The Hub reports its record of one connection as a scene: the same record
``list_clients`` returns, narrowed to one client and rendered. What a menu label
stopped carrying — the declared name, the kind, the pid inside it — is here.

A click can outlive its client, so a connection the Hub no longer holds is a
refusal, never a blank frame.
"""

from __future__ import annotations

from typing import Self, cast

from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId, Topic
from punt_lux.operations.client_details import ClientDetailsOperations
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.scene_results import SceneShown
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scene_installer import SceneInstaller
from punt_lux.protocol.elements.table import TableElement


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


class _Clock:
    """A monotonic clock the test advances by hand, so a lease lapses on cue."""

    _now: float

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._now = 0.0
        return self

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class _ForbiddenPort:
    """A DisplayPort that fails the test if the read reaches around to it."""

    def query(self, method: str, params: object) -> object:
        msg = f"Details reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> object:
        msg = f"Details reached around to the display: ping({wait!r})"
        raise AssertionError(msg)


def _wired(store: HubDisplay, hub: Hub) -> tuple[ClientDetailsOperations, _Marks]:
    """Build the details operation over real stores, with no display in reach."""
    marks = _Marks()
    queries = QueryOperations(store, hub, cast("object", _ForbiddenPort()))  # type: ignore[arg-type]  # structural port
    installer = SceneInstaller(store, marks)
    return ClientDetailsOperations(queries, installer, store.clients), marks


def _identity(name: str = "lux · lux · #4b97 · lux-beads") -> ClientIdentity:
    return ClientIdentity(kind="applet", name=name, repo="/Users/someone/lux")


def _named(store: HubDisplay, connection: str, identity: ClientIdentity) -> None:
    """Record a client and take the read that names it, as the menu build does."""
    store.identify_client(ConnectionId(connection), identity)
    store.clients.named_sessions()


def _scoped(owner: str, scene_id: str) -> SceneId:
    """The store key ``scene_id`` composes to for a Details scene owned by ``owner``.

    A Details scene is written *for* the client it describes — the wire result
    still reports the caller's own raw name, but the store holds it composed
    against that same client's own connection (DES-086).
    """
    return SceneId(ConnectionScopedId.compose(ConnectionId(owner), scene_id))


def _rows(store: HubDisplay, owner: str, scene_id: str) -> dict[str, str]:
    """Read the field/value pairs out of the installed details table."""
    root = store.scene_roots(_scoped(owner, scene_id))[0]
    assert isinstance(root, TableElement)
    return {str(row[0]): str(row[1]) for row in root.rows}


class TestWhatDetailsReports:
    """The Hub's record of one connection, rendered."""

    def test_the_scene_carries_the_wire_identity_the_label_dropped(self) -> None:
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", _identity())
        details, _marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, SceneShown)
        rows = _rows(store, "c1", result.scene_id)
        assert rows["Client"] == "lux"  # what the menu calls it
        assert rows["Declared name"] == "lux · lux · #4b97 · lux-beads"
        assert rows["Kind"] == "applet"
        assert rows["Repository"] == "/Users/someone/lux"
        assert rows["Connection"] == "c1"

    def test_it_reports_the_topics_and_scenes_the_client_holds(self) -> None:
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", _identity())
        hub.register_writer(ConnectionId("c1"), lambda _msg: None)
        hub.subscribe(ConnectionId("c1"), Topic("work.saved"))
        group = hub_element_factory(ConnectionId("c1")).element_from_dict(
            {"kind": "text", "id": "t1", "content": "hi"}
        )
        store.show_scene(
            ConnectionId("c1"),
            SceneId("board"),
            [cast("DomainElement", group)],
            ScenePresentation(frame_id="f1"),
        )
        details, _marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, SceneShown)
        rows = _rows(store, "c1", result.scene_id)
        assert rows["Topics"] == "work.saved"
        assert "board" in rows["Scenes"]

    def test_an_empty_field_reads_as_none_rather_than_blank(self) -> None:
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", ClientIdentity(kind="app", name="voxd"))
        details, _marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, SceneShown)
        rows = _rows(store, "c1", result.scene_id)
        assert rows["Repository"] == "none"
        assert rows["Agent"] == "none"
        assert rows["Topics"] == "none"
        assert rows["Scenes"] == "none"

    def test_a_lease_that_never_lapses_reads_as_permanent(self) -> None:
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", ClientIdentity(kind="app", name="voxd"))
        details, _marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, SceneShown)
        assert _rows(store, "c1", result.scene_id)["Lease"] == "permanent"

    def test_a_declared_lease_reads_as_a_span_a_person_says(self) -> None:
        store, hub = HubDisplay(), Hub()
        _named(
            store,
            "c1",
            ClientIdentity(
                kind="applet",
                name="lux · lux · #4b97 · beads",
                repo="/w/lux",
                lease_ttl=60.0,
            ),
        )
        details, _marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, SceneShown)
        assert _rows(store, "c1", result.scene_id)["Lease"] == "1m 00s"


class TestHowItIsShown:
    """Where the scene lands, and who owns it."""

    def test_the_scene_is_owned_by_the_client_it_describes(self) -> None:
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", _identity())
        details, _marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, SceneShown)
        owners = store.scene_owners(_scoped("c1", result.scene_id))
        assert [str(owner.connection_id) for owner in owners] == ["c1"]

    def test_the_frame_is_titled_for_the_client_the_menu_named(self) -> None:
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", _identity())
        details, _marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, SceneShown)
        presentation = store.frames.presentation_for(_scoped("c1", result.scene_id))
        assert presentation.frame_title == "lux — client details"

    def test_two_clients_details_are_two_scenes(self) -> None:
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", _identity())
        _named(store, "c2", ClientIdentity(kind="app", name="voxd"))
        details, _marks = _wired(store, hub)

        first = details.show_client_details(ConnectionId("c1"))
        second = details.show_client_details(ConnectionId("c2"))

        assert isinstance(first, SceneShown)
        assert isinstance(second, SceneShown)
        assert first.scene_id != second.scene_id

    def test_asking_twice_repaints_the_same_scene(self) -> None:
        """A second look at one client replaces its frame instead of stacking one."""
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", _identity())
        details, marks = _wired(store, hub)

        first = details.show_client_details(ConnectionId("c1"))
        second = details.show_client_details(ConnectionId("c1"))

        assert isinstance(first, SceneShown)
        assert isinstance(second, SceneShown)
        assert first.scene_id == second.scene_id
        composed = str(_scoped("c1", first.scene_id))
        assert marks.marked == [composed, composed]

    def test_the_install_marks_the_scene_for_the_replicator(self) -> None:
        """The Hub writes its store and marks; the replicator does every send."""
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", _identity())
        details, marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, SceneShown)
        assert marks.marked == [str(_scoped("c1", result.scene_id))]


class TestAClickThatOutlivedItsClient:
    """The menu is a replica; a lease can lapse between the paint and the pointer."""

    def test_a_connection_the_hub_no_longer_holds_is_refused(self) -> None:
        store, hub = HubDisplay(), Hub()
        details, _marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("gone"))

        assert isinstance(result, OpError)
        assert result.code == "not_found"
        assert "gone" in result.reason

    def test_a_refusal_installs_no_scene(self) -> None:
        store, hub = HubDisplay(), Hub()
        details, marks = _wired(store, hub)

        details.show_client_details(ConnectionId("gone"))

        assert marks.marked == []
        assert list(store.live_scene_ids()) == []

    def test_a_client_that_departed_after_the_paint_is_refused_and_not_recreated(
        self,
    ) -> None:
        """The entry is still on screen; the session behind it is gone.

        The refusal is the visible half. The other half is that the click leaves
        the Hub's roster exactly as the departure left it — a Details frame written
        for a departed connection would otherwise register it again and put a
        client back in ``list_clients`` that nothing is on the other end of.
        """
        store, hub = HubDisplay(), Hub()
        _named(store, "c1", _identity())
        store.drop_connection(ConnectionId("c1"))
        details, marks = _wired(store, hub)

        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, OpError)
        assert result.code == "not_found"
        assert dict(store.client_sessions()) == {}
        assert marks.marked == []
        assert list(store.live_scene_ids()) == []

    def test_a_lease_that_lapses_by_the_read_is_refused_and_not_recreated(self) -> None:
        """The read that would name the client is the read that carries it off.

        The registry sweeps lapsed sessions as it is read, so the operation's own
        read can retire the client it was about to describe. One read is all it
        takes: presence and name come from the same instant, and there is no
        second read for the sweep to fall between.
        """
        clock = _Clock()
        store, hub = HubDisplay(clock), Hub()
        _named(
            store,
            "c1",
            ClientIdentity(
                kind="applet",
                name="lux · lux · #4b97 · beads",
                repo="/w/lux",
                lease_ttl=60.0,
            ),
        )
        details, marks = _wired(store, hub)

        clock.advance(61.0)  # the lease lapses while the entry sits on screen
        result = details.show_client_details(ConnectionId("c1"))

        assert isinstance(result, OpError)
        assert result.code == "not_found"
        assert dict(store.client_sessions()) == {}
        assert marks.marked == []
        assert list(store.live_scene_ids()) == []
