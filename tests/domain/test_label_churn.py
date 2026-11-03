"""A name that moves marks the scenes it titles: the Hub pushes, never polls.

A frame's title is prefixed with its owner's roster name (DES-100). Two things move
a name: the connection being named in the first place, and a group's last member
leaving, which hands its base to a numbered survivor. Both owe the affected
scenes a resend, paid in the same step as the registry write.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.menu_presence import MarkMenusSink
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.scope import Scope
from punt_lux.protocol.elements.text import TextElement

_FIRST = ConnectionId("first")
_SECOND = ConnectionId("second")


@final
class _Marker:
    """A DirtyMarker recording the scenes marked and the menu marks."""

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


def _repo(name: str) -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name=name, repo="/w/lux")


def _wired() -> tuple[HubStoreFactory, _Marker, _Clock]:
    clock = _Clock()
    factory = HubStoreFactory(clock, Hub())
    marker = _Marker()
    factory.lifecycle.present_as(marker, MarkMenusSink(marker))
    return factory, marker, clock


def _show(factory: HubStoreFactory, conn: ConnectionId, scene: str) -> SceneId:
    scene_id = SceneId(f"{conn}-{scene}")
    factory.display.replace_scene(
        Scope.in_process(conn), scene_id, [TextElement(id="t", content="x")]
    )
    return scene_id


def _two_sessions_of_one_repo() -> tuple[
    HubStoreFactory, _Marker, _Clock, SceneId, SceneId
]:
    factory, marker, clock = _wired()
    factory.lifecycle.identify(_FIRST, _repo("a"), UNOBSERVED)
    factory.lifecycle.identify(_SECOND, _repo("b"), UNOBSERVED)
    first = _show(factory, _FIRST, "vox")
    second = _show(factory, _SECOND, "vox")
    factory.clients.named_sessions()  # the read that names them: lux, lux (2)
    marker.scenes.clear()
    return factory, marker, clock, first, second


class TestDeparture:
    def test_the_survivor_that_inherits_the_base_name_is_marked(self) -> None:
        factory, marker, _, _, second = _two_sessions_of_one_repo()

        factory.lifecycle.depart(_FIRST)

        assert marker.scenes == [second]

    def test_a_departure_that_moves_no_name_marks_nothing(self) -> None:
        factory, marker, _, _, _ = _two_sessions_of_one_repo()

        factory.lifecycle.depart(_SECOND)

        assert marker.scenes == []

    def test_a_survivor_with_several_scenes_is_marked_once_per_scene(self) -> None:
        factory, marker, _, _, second = _two_sessions_of_one_repo()
        other = _show(factory, _SECOND, "beads")
        marker.scenes.clear()

        factory.lifecycle.depart(_FIRST)

        assert sorted(marker.scenes) == sorted([second, other])

    def test_departing_a_connection_nobody_knows_marks_nothing(self) -> None:
        factory, marker, _, _, _ = _two_sessions_of_one_repo()

        factory.lifecycle.depart(ConnectionId("ghost"))

        assert marker.scenes == []

    def test_a_lease_sweep_marks_the_survivor_the_same_way(self) -> None:
        factory, marker, clock, first, second = _two_sessions_of_one_repo()
        clock.now = 2_000.0  # past both mcp leases...
        factory.lifecycle.arrive(
            _SECOND, UNOBSERVED
        )  # ...then the survivor makes contact

        lapsed = factory.lifecycle.depart_lapsed(frozenset())

        assert lapsed == frozenset({_FIRST})
        assert second in marker.scenes
        assert first not in marker.scenes


class TestIdentification:
    def test_naming_a_connection_marks_the_scenes_it_already_shows(self) -> None:
        factory, marker, _ = _wired()
        factory.lifecycle.arrive(_FIRST, UNOBSERVED)
        scene = _show(factory, _FIRST, "vox")
        marker.scenes.clear()

        factory.lifecycle.identify(_FIRST, _repo("a"), UNOBSERVED)

        assert marker.scenes == [scene]

    def test_a_client_that_registers_no_callback_is_still_retitled(self) -> None:
        # Presence cannot be the trigger: a repository-kind client with no
        # command earns no menu entry, so presence holds while it is named.
        factory, marker, _ = _wired()
        factory.lifecycle.arrive(_FIRST, UNOBSERVED)
        scene = _show(factory, _FIRST, "vox")
        marker.scenes.clear()

        factory.lifecycle.identify(
            _FIRST, ClientIdentity(kind="cli", name="cli", repo="/w/lux"), UNOBSERVED
        )

        assert marker.scenes == [scene]

    def test_repeating_the_declaration_marks_once_not_per_request(self) -> None:
        factory, marker, _ = _wired()
        factory.lifecycle.arrive(_FIRST, UNOBSERVED)
        scene = _show(factory, _FIRST, "vox")
        factory.lifecycle.identify(_FIRST, _repo("a"), UNOBSERVED)
        marker.scenes.clear()

        factory.lifecycle.identify(_FIRST, _repo("a"), UNOBSERVED)
        factory.lifecycle.identify(_FIRST, _repo("a"), UNOBSERVED)

        assert marker.scenes == []
        assert scene not in marker.scenes

    def test_an_anonymous_arrival_marks_nothing(self) -> None:
        factory, marker, _ = _wired()

        factory.lifecycle.arrive(_FIRST, UNOBSERVED)
        _show(factory, _FIRST, "vox")
        factory.lifecycle.arrive(_FIRST, UNOBSERVED)

        assert marker.scenes == []

    def test_a_changed_declaration_marks_again(self) -> None:
        factory, marker, _ = _wired()
        factory.lifecycle.identify(_FIRST, _repo("a"), UNOBSERVED)
        scene = _show(factory, _FIRST, "vox")
        marker.scenes.clear()

        factory.lifecycle.identify(
            _FIRST,
            ClientIdentity(kind="mcp-session", name="a", repo="/w/other"),
            UNOBSERVED,
        )

        assert marker.scenes == [scene]

    def test_a_listen_leg_attach_that_declares_marks_the_connections_scenes(
        self,
    ) -> None:
        factory, marker, _ = _wired()
        factory.lifecycle.arrive(_FIRST, UNOBSERVED)
        scene = _show(factory, _FIRST, "vox")
        marker.scenes.clear()

        factory.lifecycle.attach(_FIRST, _repo("a"), _Leg(), UNOBSERVED)

        assert scene in marker.scenes


@final
class _Leg:
    def wake(self) -> None:
        """Delivery is elsewhere; the leg only has to occupy the slot."""
