"""FrameOwnerFacts — resolving a scene's senior owner into the popup's rows.

Reuses exactly the Details command's facts and formatting
(ClientIdentityFacts, ClientDetails.rows()), so the popup and the Hub's own
record of a connection always agree.
"""

from __future__ import annotations

from typing import cast

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.frame_owner_facts import FrameOwnerFacts
from punt_lux.operations.queries import QueryOperations
from punt_lux.protocol.elements.text import TextElement


class _ForbiddenPort:
    """A DisplayPort that fails the test if the read reaches around to it."""

    def query(self, method: str, params: object) -> object:
        msg = f"reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> object:
        msg = f"reached around to the display: ping({wait!r})"
        raise AssertionError(msg)


def _zero_inbox_depth(_connection_id: ConnectionId) -> int:
    """Report every connection's inbox empty; these tests don't exercise it."""
    return 0


def _reader(store: HubDisplay, hub: Hub) -> FrameOwnerFacts:
    clients = ClientListing(store, hub, _zero_inbox_depth)
    queries = QueryOperations(
        store,
        cast("object", _ForbiddenPort()),  # type: ignore[arg-type]  # structural port
        clients,
    )
    return FrameOwnerFacts(store, queries)


def _identified_scene(store: HubDisplay, connection: str, name: str = "lux") -> SceneId:
    """Register a named client and install one root it owns, returning its scene id."""
    conn = ConnectionId(connection)
    store.identify_client(conn, ClientIdentity(kind="cli", name=name))
    store.clients.named_sessions()  # the read that names it, as the menu build does
    scene_id = SceneId(f"{connection}-scene")
    store.replace_scene(conn, scene_id, [TextElement(id="t1", content="hi")])
    return scene_id


class TestASceneWithALiveOwner:
    def test_reports_the_owners_rows(self) -> None:
        store, hub = HubDisplay(), Hub()
        scene_id = _identified_scene(store, "c1")
        reader = _reader(store, hub)

        rows = reader.facts_for(scene_id)

        assert rows is not None
        fields = dict(rows)
        assert fields["Client"] == "lux"
        assert fields["Kind"] == "cli"
        assert fields["Connection"] == "c1"

    def test_field_order_matches_client_details_rows(self) -> None:
        store, hub = HubDisplay(), Hub()
        scene_id = _identified_scene(store, "c1")
        reader = _reader(store, hub)

        rows = reader.facts_for(scene_id)

        assert rows is not None
        assert [label for label, _ in rows] == [
            "Client",
            "Kind",
            "Declared name",
            "Repository",
            "Agent",
            "Connection",
            "Connected",
            "Lease",
            "Topics",
            "Scenes",
        ]

    def test_uses_the_senior_first_appearance_owner(self) -> None:
        # Two connections both install roots in one scene (AddElement, not
        # replace_scene, so both roots stand); the senior owner (first-
        # appearance order) is the one Details points at too.
        store, hub = HubDisplay(), Hub()
        c1, c2 = ConnectionId("c1"), ConnectionId("c2")
        store.register_client(c1)
        store.register_client(c2)
        store.identify_client(c1, ClientIdentity(kind="app", name="a"))
        store.identify_client(c2, ClientIdentity(kind="app", name="b"))
        store.clients.named_sessions()
        scene_id = SceneId("shared")
        store.apply(
            c1,
            AddElement(
                scene_id=scene_id,
                element=TextElement(id="t1", content="x"),
                parent_id=None,
            ),
        )
        store.apply(
            c2,
            AddElement(
                scene_id=scene_id,
                element=TextElement(id="t2", content="y"),
                parent_id=None,
            ),
        )
        reader = _reader(store, hub)

        rows = reader.facts_for(scene_id)

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"


class TestASceneWithNoOwner:
    def test_an_unowned_scene_reports_none(self) -> None:
        store, hub = HubDisplay(), Hub()
        reader = _reader(store, hub)

        assert reader.facts_for(SceneId("nobody-installed-this")) is None

    def test_a_scene_whose_owner_departed_reports_none(self) -> None:
        # The Hub-side departure guarantee: OwnerTracker releases the departed
        # connection's records, so the reader can no longer resolve a session
        # for it -- the display's cached snapshot from before departure is
        # what preserves the popup's last-known facts, not this reader.
        store, hub = HubDisplay(), Hub()
        scene_id = _identified_scene(store, "c1")
        store.drop_connection(ConnectionId("c1"))
        reader = _reader(store, hub)

        assert reader.facts_for(scene_id) is None
