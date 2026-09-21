"""CanonicalFrameOwner — owner facts lifted from a scene to its whole frame.

Wraps FrameOwnerFacts: every scene composed into one frame must resolve to the
same owner, whichever scene the replicator sent last.
"""

from __future__ import annotations

from typing import cast

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.canonical_frame_owner import CanonicalFrameOwner
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


def _reader(store: HubDisplay, hub: Hub) -> CanonicalFrameOwner:
    clients = ClientListing(store, hub, _zero_inbox_depth)
    queries = QueryOperations(
        store,
        cast("object", _ForbiddenPort()),  # type: ignore[arg-type]  # structural port
        clients,
    )
    return CanonicalFrameOwner(store, FrameOwnerFacts(store, queries))


def _identified_scene(store: HubDisplay, connection: str, name: str) -> SceneId:
    """Register a named client and install one root it owns, returning its scene id."""
    conn = ConnectionId(connection)
    store.identify_client(conn, ClientIdentity(kind="cli", name=name))
    store.clients.named_sessions()  # the read that names it, as the menu build does
    scene_id = SceneId(f"{connection}-scene")
    store.replace_scene(conn, scene_id, [TextElement(id="t1", content="hi")])
    return scene_id


class TestAFrameComposingScenesWithDifferentOwners:
    def test_resolves_one_canonical_owner_regardless_of_send_order(self) -> None:
        # Two scenes, each owned by a different senior connection, share one
        # frame. The replicator resends each scene separately; the owner must
        # resolve the same whichever scene was sent (asked about) last.
        store, hub = HubDisplay(), Hub()
        first = _identified_scene(store, "c1", name="alpha")
        second = _identified_scene(store, "c2", name="beta")
        frame = ScenePresentation(frame_id="shared-frame")
        store.frames.record(first, frame)
        store.frames.record(second, frame)
        reader = _reader(store, hub)

        by_first = reader.facts_for(first)
        by_second = reader.facts_for(second)

        assert by_first is not None
        assert by_first == by_second
        assert dict(by_first)["Connection"] == "c1"

    def test_seniority_is_first_appearance_not_lexical_scene_id(self) -> None:
        # The frame first receives "z-scene" (owner "z"), then "a-scene"
        # (owner "a"). Seniority is first-appearance order, so the canonical
        # owner is "z" -- lexical scene-id order would wrongly pick "a".
        store, hub = HubDisplay(), Hub()
        senior = _identified_scene(store, "z", name="alpha")
        junior = _identified_scene(store, "a", name="beta")
        frame = ScenePresentation(frame_id="shared-frame")
        store.frames.record(senior, frame)
        store.frames.record(junior, frame)
        reader = _reader(store, hub)

        by_senior = reader.facts_for(senior)
        by_junior = reader.facts_for(junior)

        assert by_senior is not None
        assert by_senior == by_junior  # order-independent of the triggering send
        assert dict(by_senior)["Connection"] == "z"


class TestASelfFramedScene:
    def test_reports_its_own_owner(self) -> None:
        # A scene with no shared frame resolves to its own owner unchanged.
        store, hub = HubDisplay(), Hub()
        scene_id = _identified_scene(store, "c1", name="alpha")
        reader = _reader(store, hub)

        rows = reader.facts_for(scene_id)

        assert rows is not None
        assert dict(rows)["Connection"] == "c1"

    def test_an_unowned_scene_reports_none(self) -> None:
        store, hub = HubDisplay(), Hub()
        reader = _reader(store, hub)

        assert reader.facts_for(SceneId("nobody-installed-this")) is None
