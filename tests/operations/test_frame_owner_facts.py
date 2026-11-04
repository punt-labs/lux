"""FrameOwnerFacts — resolving a scene's senior owner into the popup's rows.

Reuses exactly the Details command's facts and formatting
(ClientIdentityFacts, ClientDetails.rows()), so the popup and the Hub's own
record of a connection always agree.
"""

from __future__ import annotations

from punt_lux.client_host import UNOBSERVED, ClientHost
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
from punt_lux.domain.hub.frame_ownership import FrameOwnership
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.lease_term import LeaseTerms
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.scope import Scope
from punt_lux.domain.update import AddElement
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.frame_owner_facts import FrameOwnerFacts
from punt_lux.protocol.compositions.client_details import ClientDetails
from punt_lux.protocol.elements.text import TextElement


def _zero_inbox_depth(_connection_id: ConnectionId) -> int:
    """Report every connection's inbox empty; these tests don't exercise it."""
    return 0


def _reader(store: HubDisplay, clients: HubClientRegistry, hub: Hub) -> FrameOwnerFacts:
    listing = ClientListing(store, clients, hub, _zero_inbox_depth)
    return FrameOwnerFacts(store, listing)


def _identified_scene(
    store: HubDisplay,
    lifecycle: ClientLifecycle,
    clients: HubClientRegistry,
    connection: str,
    name: str = "lux",
) -> SceneId:
    """Register a named client and install one root it owns, returning its scene id."""
    conn = ConnectionId(connection)
    lifecycle.identify(conn, ClientIdentity(kind="cli", name=name), UNOBSERVED)
    clients.named_sessions()  # the read that names it, as the menu build does
    scene_id = SceneId(f"{connection}-scene")
    store.replace_scene(
        Scope.in_process(conn), scene_id, [TextElement(id="t1", content="hi")]
    )
    return scene_id


class TestTheHostRowsInThePopup:
    """The popup and the Details table are one ``ClientDetails.rows()``."""

    def test_the_popup_reports_the_observed_host_and_the_hubs_own(self) -> None:
        factory = HubStoreFactory()
        store, lifecycle, clients = factory.display, factory.lifecycle, factory.clients
        hub = Hub()
        conn = ConnectionId("c1")
        lifecycle.identify(
            conn, ClientIdentity(kind="cli", name="lux"), ClientHost("127.0.0.1")
        )
        clients.named_sessions()
        scene_id = SceneId("c1-scene")
        store.replace_scene(
            Scope.in_process(conn), scene_id, [TextElement(id="t1", content="hi")]
        )

        rows = _reader(store, clients, hub).facts_for(scene_id).rows

        assert rows is not None
        fields = dict(rows)
        assert fields["Client host"] == "127.0.0.1"
        assert fields["Hub host"] == hub.hostname

    def test_the_host_rows_follow_the_connection_row(self) -> None:
        factory = HubStoreFactory()
        store, lifecycle, clients = factory.display, factory.lifecycle, factory.clients
        scene_id = _identified_scene(store, lifecycle, clients, "c1")

        rows = _reader(store, clients, Hub()).facts_for(scene_id).rows

        assert rows is not None
        labels = [label for label, _ in rows]
        assert labels[labels.index("Connection") + 1 :][:2] == [
            "Client host",
            "Hub host",
        ]


class TestASceneWithALiveOwner:
    def test_reports_the_owners_rows(self) -> None:
        factory = HubStoreFactory()
        store = factory.display
        lifecycle = factory.lifecycle
        clients = factory.clients
        hub = Hub()
        scene_id = _identified_scene(store, lifecycle, clients, "c1")
        reader = _reader(store, clients, hub)

        ownership = reader.facts_for(scene_id)
        rows = ownership.rows

        assert rows is not None
        fields = dict(rows)
        assert fields["Client"] == "lux"
        assert fields["Kind"] == "cli"
        assert fields["Connection"] == "c1"
        assert ownership.scope_label == "lux"

    def test_field_order_matches_client_details_rows(self) -> None:
        # Proves the shared-source reuse the module docstring claims: the
        # labels come from a live ClientDetails.rows() call, not a parallel
        # hardcoded snapshot that could silently drift from the real order.
        factory = HubStoreFactory()
        store = factory.display
        lifecycle = factory.lifecycle
        clients = factory.clients
        hub = Hub()
        scene_id = _identified_scene(store, lifecycle, clients, "c1")
        reader = _reader(store, clients, hub)

        ownership = reader.facts_for(scene_id)
        rows = ownership.rows

        canonical = ClientDetails(
            label="lux",
            connection_id="c1",
            kind="cli",
            name="lux",
            connected_seconds=0.0,
            lease=LeaseTerms.of(float("inf")),
        ).rows()

        assert rows is not None
        assert [label for label, _ in rows] == [label for label, _ in canonical]

    def test_uses_the_senior_first_appearance_owner(self) -> None:
        # Two connections both install roots in one scene (AddElement, not
        # replace_scene, so both roots stand); the senior owner (first-
        # appearance order) is the one Details points at too.
        factory = HubStoreFactory()
        store = factory.display
        lifecycle = factory.lifecycle
        clients = factory.clients
        hub = Hub()
        c1, c2 = ConnectionId("c1"), ConnectionId("c2")
        lifecycle.arrive(c1, UNOBSERVED)
        lifecycle.arrive(c2, UNOBSERVED)
        lifecycle.identify(c1, ClientIdentity(kind="app", name="a"), UNOBSERVED)
        lifecycle.identify(c2, ClientIdentity(kind="app", name="b"), UNOBSERVED)
        clients.named_sessions()
        scene_id = SceneId("shared")
        store.apply(
            Scope.in_process(c1),
            AddElement(
                scene_id=scene_id,
                element=TextElement(id="t1", content="x"),
                parent_id=None,
            ),
        )
        store.apply(
            Scope.in_process(c2),
            AddElement(
                scene_id=scene_id,
                element=TextElement(id="t2", content="y"),
                parent_id=None,
            ),
        )
        reader = _reader(store, clients, hub)

        ownership = reader.facts_for(scene_id)
        rows = ownership.rows

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"


class TestASceneWithNoOwner:
    def test_an_unowned_scene_reports_none(self) -> None:
        factory = HubStoreFactory()
        store = factory.display
        clients = factory.clients
        hub = Hub()
        reader = _reader(store, clients, hub)

        assert reader.facts_for(SceneId("nobody-installed-this")) == FrameOwnership()

    def test_a_scene_whose_owner_departed_reports_none(self) -> None:
        # The Hub-side departure guarantee: OwnerTracker releases the departed
        # connection's records, so the reader can no longer resolve a session
        # for it -- the display's cached snapshot from before departure is
        # what preserves the popup's last-known facts, not this reader.
        factory = HubStoreFactory()
        store = factory.display
        clients = factory.clients
        lifecycle = factory.lifecycle
        hub = Hub()
        scene_id = _identified_scene(store, lifecycle, clients, "c1")
        lifecycle.depart(ConnectionId("c1"))
        reader = _reader(store, clients, hub)

        assert reader.facts_for(scene_id) == FrameOwnership()
