"""ClientLifecycle's callback steps: register and detach settle presence themselves.

A callback is what makes a non-agent earn a Clients entry, so writing one is a
presence transition like any other: the store lock is held, the menus are marked,
and the one shared sink is bound, all in the same step. The caller compares
nothing and remembers nothing. Presence is lease-filtered, but a withdrawal reads
``revised`` whatever the lease says, so an entry still on the Display is never
left behind.
"""

from __future__ import annotations

import threading
from typing import Self, final

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.menu_listing import MenuListing
from punt_lux.domain.hub.menu_presence import MarkMenusSink
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.scope import Scope

_CONN = ConnectionId("c1")
_CALLBACK = SessionCallback(id="run", label="Run")
# An applet's lease is 60 s and an agent's 1800 s; these step past each.
_PAST_AN_APPLET_LEASE = 100.0
_PAST_AN_AGENT_LEASE = 2000.0


@final
class _Marker:
    """A DirtyMarker counting menu marks and recording scene marks."""

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


def _applet() -> ClientIdentity:
    return ClientIdentity(kind="applet", name="lux · lux · #1 · beads", repo="/w/lux")


def _agent() -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


def _cli() -> ClientIdentity:
    return ClientIdentity(kind="cli", name="lux", repo="/w/lux")


def _wired() -> tuple[HubStoreFactory, _Marker, _Clock]:
    clock = _Clock()
    factory = HubStoreFactory(clock, Hub())
    marker = _Marker()
    factory.lifecycle.present_as(marker, MarkMenusSink(marker))
    return factory, marker, clock


def _registered_applet() -> tuple[HubStoreFactory, _Marker, _Clock, _Leg]:
    factory, marker, clock = _wired()
    leg = _Leg()
    factory.lifecycle.attach(_CONN, _applet(), leg, UNOBSERVED)
    assert (
        factory.lifecycle.register_callback(_CONN, _CALLBACK, UNOBSERVED)
        == "registered"
    )
    return factory, marker, clock, leg


def _departure_marks(factory: HubStoreFactory, marker: _Marker) -> int:
    """How many menu marks one departure of the connection raises: sinks fired."""
    before = marker.menus
    factory.lifecycle.depart(_CONN)
    return marker.menus - before


class TestRegistering:
    def test_marks_the_menus_and_binds_exactly_one_sink(self) -> None:
        factory, marker, _ = _wired()
        factory.lifecycle.attach(_CONN, _applet(), _Leg(), UNOBSERVED)
        before = marker.menus

        outcome = factory.lifecycle.register_callback(_CONN, _CALLBACK, UNOBSERVED)

        assert outcome == "registered"
        assert marker.menus > before
        assert _departure_marks(factory, marker) == 1

    def test_registering_again_still_leaves_one_sink(self) -> None:
        factory, marker, _, _ = _registered_applet()

        factory.lifecycle.register_callback(
            _CONN, SessionCallback(id="more", label="More"), UNOBSERVED
        )

        assert _departure_marks(factory, marker) == 1

    def test_an_applet_that_registers_then_lapses_is_departed_with_one_mark(
        self,
    ) -> None:
        factory, marker, clock, _ = _registered_applet()
        clock.now = _PAST_AN_APPLET_LEASE
        before = marker.menus

        lapsed = factory.lifecycle.depart_lapsed(frozenset())

        assert lapsed == frozenset({_CONN})
        assert marker.menus - before == 1

    def test_a_callback_only_applet_departs_with_a_mark_when_dropped(self) -> None:
        factory, marker, _, _ = _registered_applet()

        assert _departure_marks(factory, marker) == 1

    def test_is_one_step_under_the_store_lock(self) -> None:
        factory, _, _ = _wired()
        factory.lifecycle.attach(_CONN, _applet(), _Leg(), UNOBSERVED)
        done = threading.Event()

        def register() -> None:
            factory.lifecycle.register_callback(_CONN, _CALLBACK, UNOBSERVED)
            done.set()

        with factory.lifecycle.exclusive():
            worker = threading.Thread(target=register)
            worker.start()
            assert not done.wait(0.3)
        worker.join(timeout=5)

        assert done.is_set()

    def test_is_refused_with_no_leg_and_marks_and_binds_nothing(self) -> None:
        factory, marker, _ = _wired()
        factory.lifecycle.arrive(_CONN, UNOBSERVED)  # registered, anonymous, no leg

        outcome = factory.lifecycle.register_callback(_CONN, _CALLBACK, UNOBSERVED)

        assert outcome == "superseded"
        assert marker.menus == 0
        assert _departure_marks(factory, marker) == 0

    def test_is_refused_for_an_unknown_connection(self) -> None:
        factory, marker, _ = _wired()

        outcome = factory.lifecycle.register_callback(
            ConnectionId("ghost"), _CALLBACK, UNOBSERVED
        )

        assert outcome == "superseded"
        assert marker.menus == 0

    def test_revives_a_lapsed_but_reachable_applet_with_one_sink_and_marks_its_scenes(
        self,
    ) -> None:
        factory, marker, clock = _wired()
        factory.lifecycle.attach(_CONN, _applet(), _Leg(), UNOBSERVED)
        scene = SceneId("s1")
        from punt_lux.protocol.elements.text import TextElement

        factory.display.replace_scene(
            Scope.in_process(_CONN), scene, [TextElement(id="t", content="x")]
        )
        clock.now = _PAST_AN_APPLET_LEASE
        marker.scenes.clear()
        before = marker.menus

        outcome = factory.lifecycle.register_callback(_CONN, _CALLBACK, UNOBSERVED)

        assert outcome == "registered"
        assert marker.menus > before
        assert scene in marker.scenes
        assert _departure_marks(factory, marker) == 1


class TestDetaching:
    def test_a_callback_only_applet_withdraws_its_entry_and_keeps_session_and_sink(
        self,
    ) -> None:
        factory, marker, clock, leg = _registered_applet()
        before = marker.menus

        outcome = factory.lifecycle.detach(_CONN, leg)

        assert outcome == "released_with_callbacks"
        assert marker.menus > before
        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert not MenuListing(session, clock.now).holds()
        assert _departure_marks(factory, marker) == 1

    def test_a_lapsed_callback_only_applet_still_marks_the_withdrawal(self) -> None:
        # The entry is still on the Display: a lapse is time, not a Hub event.
        factory, marker, clock, leg = _registered_applet()
        clock.now = _PAST_AN_APPLET_LEASE
        before = marker.menus

        factory.lifecycle.detach(_CONN, leg)

        assert marker.menus > before

    def test_an_agent_holding_callbacks_stays_listed_and_keeps_its_sink(self) -> None:
        factory, marker, clock = _wired()
        leg = _Leg()
        factory.lifecycle.attach(_CONN, _agent(), leg, UNOBSERVED)
        factory.lifecycle.register_callback(_CONN, _CALLBACK, UNOBSERVED)

        factory.lifecycle.detach(_CONN, leg)

        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert MenuListing(session, clock.now).holds()
        assert _departure_marks(factory, marker) == 1

    def test_a_session_that_lost_the_slot_clears_nothing_and_marks_nothing(
        self,
    ) -> None:
        factory, marker, _, old = _registered_applet()
        factory.lifecycle.attach(_CONN, _applet(), _Leg(), UNOBSERVED)
        factory.lifecycle.register_callback(_CONN, _CALLBACK, UNOBSERVED)
        before = marker.menus

        outcome = factory.lifecycle.detach(_CONN, old)

        assert outcome == "kept"
        assert marker.menus == before

    def test_an_unknown_connection_is_released_with_its_session(self) -> None:
        factory, marker, _ = _wired()

        outcome = factory.lifecycle.detach(ConnectionId("ghost"), _Leg())

        assert outcome == "released_with_session"
        assert marker.menus == 0

    def test_is_one_step_under_the_store_lock(self) -> None:
        factory, _, _, leg = _registered_applet()
        done = threading.Event()

        def detach() -> None:
            factory.lifecycle.detach(_CONN, leg)
            done.set()

        with factory.lifecycle.exclusive():
            worker = threading.Thread(target=detach)
            worker.start()
            assert not done.wait(0.3)
        worker.join(timeout=5)

        assert done.is_set()


class TestAttachingOverCallbacks:
    def test_the_callbacks_of_a_lapsed_applet_are_cleared_with_a_mark(self) -> None:
        factory, marker, clock, _ = _registered_applet()
        clock.now = _PAST_AN_APPLET_LEASE
        before = marker.menus

        factory.lifecycle.attach(_CONN, _applet(), _Leg(), UNOBSERVED)

        assert marker.menus > before


class TestReDeclaring:
    def test_a_lapsed_agent_re_identifying_as_a_cli_marks_and_stays_gone(self) -> None:
        factory, marker, clock = _wired()
        factory.lifecycle.identify(_CONN, _agent(), UNOBSERVED)
        clock.now = _PAST_AN_AGENT_LEASE
        before = marker.menus

        factory.lifecycle.identify(_CONN, _cli(), UNOBSERVED)

        assert marker.menus > before
        after = marker.menus
        factory.lifecycle.contact(Scope.in_process(_CONN))
        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert not MenuListing(session, clock.now).holds()
        assert marker.menus == after

    def test_a_live_agent_re_identifying_as_a_cli_marks(self) -> None:
        factory, marker, _ = _wired()
        factory.lifecycle.identify(_CONN, _agent(), UNOBSERVED)
        before = marker.menus

        factory.lifecycle.identify(_CONN, _cli(), UNOBSERVED)

        assert marker.menus > before


class TestTheWithdrawalRule:
    """Earned before, ignoring the lease, and not earning after reads revised."""

    def _earning(self) -> ClientSession:
        return (
            ClientSession(0.0)
            .with_identity(_applet())
            .attached(_Leg())
            .registering(_CALLBACK, 1.0)  # type: ignore[return-value]
        )

    def _withdrawn(self) -> ClientSession:
        return ClientSession(0.0).with_identity(_applet())

    def test_a_live_withdrawal_is_revised(self) -> None:
        before = MenuListing(self._earning(), 2.0)

        assert before.change_to(MenuListing(self._withdrawn(), 2.0)) == "revised"

    def test_a_lapsed_withdrawal_is_revised_too(self) -> None:
        before = MenuListing(self._earning(), 1000.0)

        assert before.change_to(MenuListing(self._withdrawn(), 1000.0)) == "revised"

    def test_a_session_that_never_earned_reads_unchanged(self) -> None:
        before = MenuListing(self._withdrawn(), 1000.0)

        assert before.change_to(MenuListing(self._withdrawn(), 1000.0)) == "unchanged"

    def test_a_gain_still_reads_the_lease(self) -> None:
        before = MenuListing(self._withdrawn(), 2.0)

        assert before.change_to(MenuListing(self._earning(), 2.0)) == "gained"


class TestAnAppletAttachingWithNoCallback:
    def test_marks_nothing_and_binds_no_sink(self) -> None:
        factory, marker, _ = _wired()

        factory.lifecycle.attach(_CONN, _applet(), _Leg(), UNOBSERVED)

        assert marker.menus == 0
        assert _departure_marks(factory, marker) == 0


class TestARenewingAgent:
    def test_keeps_its_entry_across_reap_opportunities(self) -> None:
        factory, marker, clock = _wired()
        factory.lifecycle.identify(_CONN, _agent(), UNOBSERVED)
        before = marker.menus

        for _ in range(3):
            clock.now += 1000.0  # inside the 1800 s agent lease if renewed each time
            factory.lifecycle.contact(Scope.in_process(_CONN))
            assert factory.lifecycle.depart_lapsed(frozenset()) == frozenset()

        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert MenuListing(session, clock.now).holds()
        assert marker.menus == before  # a renewed agent is never swept or re-marked
