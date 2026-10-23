"""A revival retitles the scenes: a frame's label is read from live sessions only.

A session whose lease lapsed but was not swept resolves to no label, so a frame
repushed in that window keeps the title it had, or loses its label. When the
session comes back, every step that ends the lapse owes that connection's scenes
a resend, whether or not the session earns a Clients entry, and a renewal of a
live session owes nothing.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.menu_presence import MarkMenusSink
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.frame_owner_facts import FrameOwnerFacts
from punt_lux.protocol.elements.text import TextElement

_CONN = ConnectionId("c1")
_OTHER = ConnectionId("c2")
_PAST_AN_AGENT_LEASE = 2000.0
_PAST_A_CLI_LEASE = 100.0


@final
class _Marker:
    scenes: list[SceneId]
    menus: int
    __slots__ = ("menus", "scenes")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.scenes = []
        self.menus = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.scenes.append(scene_id)

    def mark_menus(self) -> None:
        self.menus += 1


@final
class _Clock:
    now: float
    __slots__ = ("now",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.now = 0.0
        return self

    def __call__(self) -> float:
        return self.now


@final
class _Leg:
    def wake(self) -> None:
        """Occupies the slot only."""


def _agent(repo: str = "/w/lux") -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name="claude", repo=repo)


def _cli() -> ClientIdentity:
    return ClientIdentity(kind="cli", name="lux", repo="/w/lux")


def _applet() -> ClientIdentity:
    return ClientIdentity(kind="applet", name="lux · lux · #1 · beads", repo="/w/lux")


def _wired() -> tuple[HubStoreFactory, _Marker, _Clock]:
    clock = _Clock()
    factory = HubStoreFactory(clock, Hub())
    marker = _Marker()
    factory.lifecycle.present_as(marker, MarkMenusSink(marker))
    return factory, marker, clock


def _show(factory: HubStoreFactory, conn: ConnectionId, name: str) -> SceneId:
    scene = SceneId(f"{conn}-{name}")
    factory.display.replace_scene(conn, scene, [TextElement(id="t", content="x")])
    return scene


def _lapsed_agent() -> tuple[HubStoreFactory, _Marker, _Clock, SceneId]:
    factory, marker, clock = _wired()
    factory.lifecycle.identify(_CONN, _agent())
    scene = _show(factory, _CONN, "vox")
    clock.now = _PAST_AN_AGENT_LEASE
    marker.scenes.clear()
    return factory, marker, clock, scene


class TestEveryStepThatEndsALapseMarksTheScenes:
    def test_renew(self) -> None:
        factory, marker, _, scene = _lapsed_agent()

        factory.lifecycle.renew(_CONN)

        assert marker.scenes == [scene]

    def test_arrive(self) -> None:
        factory, marker, _, scene = _lapsed_agent()

        factory.lifecycle.arrive(_CONN)

        assert marker.scenes == [scene]

    def test_identify_with_the_same_declaration(self) -> None:
        factory, marker, _, scene = _lapsed_agent()

        factory.lifecycle.identify(_CONN, _agent())

        assert marker.scenes == [scene]

    def test_attach(self) -> None:
        factory, marker, _, scene = _lapsed_agent()

        factory.lifecycle.attach(_CONN, _agent(), _Leg())

        assert marker.scenes == [scene]

    def test_register_callback(self) -> None:
        factory, marker, clock = _wired()
        factory.lifecycle.attach(_CONN, _applet(), _Leg())
        scene = _show(factory, _CONN, "vox")
        clock.now = 100.0  # past an applet's 60 s lease
        marker.scenes.clear()

        factory.lifecycle.register_callback(
            _CONN, SessionCallback(id="run", label="Run")
        )

        assert scene in marker.scenes

    def test_a_session_that_earns_nothing_is_revived_too(self) -> None:
        # The lapse ending is the trigger, not a change to who the menu lists.
        factory, marker, clock = _wired()
        factory.lifecycle.identify(_CONN, _cli())
        scene = _show(factory, _CONN, "vox")
        clock.now = _PAST_A_CLI_LEASE
        marker.scenes.clear()

        factory.lifecycle.renew(_CONN)

        assert marker.scenes == [scene]

    def test_a_live_renewal_marks_no_scenes(self) -> None:
        factory, marker, clock = _wired()
        factory.lifecycle.identify(_CONN, _agent())
        _show(factory, _CONN, "vox")
        clock.now = 10.0  # well inside the lease
        marker.scenes.clear()

        factory.lifecycle.renew(_CONN)

        assert marker.scenes == []

    def test_a_renewal_marks_only_the_revived_connections_scenes(self) -> None:
        factory, marker, clock = _wired()
        factory.lifecycle.identify(_CONN, _agent())
        factory.lifecycle.identify(_OTHER, _agent("/w/other"))
        mine = _show(factory, _CONN, "vox")
        _show(factory, _OTHER, "vox")
        clock.now = _PAST_AN_AGENT_LEASE
        factory.lifecycle.renew(_OTHER)
        marker.scenes.clear()

        factory.lifecycle.renew(_CONN)

        assert marker.scenes == [mine]

    def test_the_second_renewal_marks_nothing_more(self) -> None:
        factory, marker, _, _ = _lapsed_agent()
        factory.lifecycle.renew(_CONN)
        marker.scenes.clear()

        factory.lifecycle.renew(_CONN)

        assert marker.scenes == []

    def test_a_swept_connection_has_no_scenes_left_to_mark(self) -> None:
        factory, marker, _, _ = _lapsed_agent()
        factory.lifecycle.depart_lapsed(frozenset())
        marker.scenes.clear()

        factory.lifecycle.arrive(_CONN)

        assert marker.scenes == []


def _facts(factory: HubStoreFactory) -> FrameOwnerFacts:
    listing = ClientListing(factory.display, factory.clients, Hub(), lambda _c: 0)
    return FrameOwnerFacts(factory.display, listing)


class TestTheLabelFollowsTheRevival:
    def test_a_lapsed_unswept_owner_reports_no_label(self) -> None:
        factory, _, _, scene = _lapsed_agent()

        assert _facts(factory).facts_for(scene).scope_label is None

    def test_an_emptied_frame_blanked_for_a_lapsed_owner_is_repaired_by_revival(
        self,
    ) -> None:
        factory, marker, _, scene = _lapsed_agent()
        factory.clients.named_sessions()
        blanked = _facts(factory).facts_for(scene).scope_label  # relabel(None) time
        assert blanked is None

        factory.lifecycle.renew(_CONN)

        assert scene in marker.scenes
        assert _facts(factory).facts_for(scene).scope_label == "lux"

    def test_a_renumbered_lapsed_survivor_shows_its_current_label_after_reviving(
        self,
    ) -> None:
        factory, marker, clock = _wired()
        factory.lifecycle.identify(_CONN, _agent())
        factory.lifecycle.identify(_OTHER, _agent())
        _show(factory, _CONN, "vox")
        survivor = _show(factory, _OTHER, "vox")
        factory.clients.named_sessions()  # lux, lux (2)
        assert _facts(factory).facts_for(survivor).scope_label == "lux (2)"
        clock.now = _PAST_AN_AGENT_LEASE
        factory.lifecycle.renew(_CONN)  # the senior stays live...
        factory.lifecycle.depart(_CONN)  # ...then leaves; the survivor is lapsed
        assert _facts(factory).facts_for(survivor).scope_label is None
        marker.scenes.clear()

        factory.lifecycle.renew(_OTHER)

        assert survivor in marker.scenes
        assert _facts(factory).facts_for(survivor).scope_label == "lux"
