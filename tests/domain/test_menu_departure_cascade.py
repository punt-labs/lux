"""D2: a menu owner's lease-lapse departure withdraws its bar from the registry.

The Hub owns the agent menu bar keyed by the owning session (MO: ``menuOwner ⊆
registered``, modelled in ``docs/menu_lifecycle.tex``). Before the fix, only the
graceful ``session_cleanup`` leg pruned a departed owner's bar; a lease-lapse
departure (the timer's own sweep) left the registry entry standing, so a
``menuOwner`` outlived its ``registered`` session. The fix binds a
:class:`~punt_lux.operations.menus.MenuDepartureSink` as a departure sink at the
``menu_set`` admit moment, so EVERY departure trigger both prunes the bar AND
marks it dirty for re-push -- exercised here through the real :class:`MenuArming`
admit path and the production sink, not a hand-bound prune.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.menu_models import Menu
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.menu_arming import MenuArming
from punt_lux.operations.menus import MenuDepartureSink


class _Clock:
    """A hand-advanced monotonic clock, so lease expiry is deterministic."""

    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@final
class _MarkerSpy:
    """A DirtyMarker counting the menu re-push signals the sink raises."""

    _menu_marks: int
    __slots__ = ("_menu_marks",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._menu_marks = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError("a departure sink must not mark a scene dirty")

    def mark_menus(self) -> None:
        self._menu_marks += 1

    @property
    def menu_marks(self) -> int:
        """How many times the departed bar was flagged for re-push."""
        return self._menu_marks


def _cli(name: str) -> ClientIdentity:
    """A ``cli``-kind identity — the 90s lease the reaping tests advance past."""
    return ClientIdentity(kind="cli", name=name, repo="/w/lux")


def _armed(
    hub_display: HubDisplay, registry: HubMenuRegistry, marker: _MarkerSpy
) -> MenuArming:
    """MenuArming wired exactly as ``facade.for_store`` wires it, over a test store.

    The third argument — the departure arm — binds the production
    :class:`MenuDepartureSink`, which prunes the registry AND marks the bar dirty.
    """
    sink = MenuDepartureSink(registry, marker)
    return MenuArming(
        hub_display.clients,
        lambda _cid: None,  # ensure_writer: incidental to the departure leg
        lambda cid: hub_display.bind_departure_sink(cid, sink),
    )


def test_a_lease_lapse_departure_withdraws_the_sessions_menu() -> None:
    """D2: the timer's sweep alone prunes a lapsed menu owner's bar.

    Fail-on-current if the admit path stops binding the registry prune as a
    departure sink: the sweep would then reap the connection without pruning the
    bar, leaving a ``menuOwner`` with no ``registered`` session behind it.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    registry = HubMenuRegistry(hub_display.clients)
    arming = _armed(hub_display, registry, _MarkerSpy())

    conn = ConnectionId("agent")
    hub_display.identify_client(conn, _cli("agent"))
    registry.set_menus(conn, [Menu(label="Tools", items=[])])
    assert arming.admit(conn) is True  # binds the registry prune as a departure sink

    clock.advance(91.0)  # past the 90s cli lease; nothing renews
    reaped = hub_display.reap_lapsed_leases()  # the timer's own sweep, nothing else

    assert reaped == frozenset({conn})
    # MO: no menuOwner outlives its registration — the prune sink ran on departure.
    assert registry._by_owner == {}
    assert registry.menu_bar() == []


def test_a_lease_lapse_departure_marks_the_menu_bar_for_re_push() -> None:
    """F3: the lease-lapse sink re-pushes, so the ghost bar leaves the Display.

    The lease-lapse path bound only ``registry.drop_session`` before: it pruned
    Hub memory but never marked the bar dirty, so the departed owner's entries
    stayed rendered until some other push. The production
    :class:`MenuDepartureSink` marks menus on departure. Fail-on-current: the
    old registry-only sink left ``menu_marks`` at zero.
    """
    clock = _Clock()
    hub_display = HubDisplay(clock)
    registry = HubMenuRegistry(hub_display.clients)
    marker = _MarkerSpy()
    arming = _armed(hub_display, registry, marker)

    conn = ConnectionId("agent")
    hub_display.identify_client(conn, _cli("agent"))
    registry.set_menus(conn, [Menu(label="Tools", items=[])])
    assert arming.admit(conn) is True

    clock.advance(91.0)  # past the 90s cli lease; nothing renews
    assert hub_display.reap_lapsed_leases() == frozenset({conn})

    # The re-push was flagged, so the replicator drops the ghost bar next send.
    assert marker.menu_marks == 1
    assert registry.menu_bar() == []


def test_a_renewing_menu_owner_keeps_its_bar_across_reap_opportunities() -> None:
    """D2 companion: an owner that keeps renewing is never swept, so its bar stands."""
    clock = _Clock()
    hub_display = HubDisplay(clock)
    registry = HubMenuRegistry(hub_display.clients)
    marker = _MarkerSpy()
    arming = _armed(hub_display, registry, marker)

    conn = ConnectionId("steady")
    hub_display.identify_client(conn, _cli("steady"))
    registry.set_menus(conn, [Menu(label="Tools", items=[])])
    assert arming.admit(conn) is True

    for _ in range(3):
        clock.advance(60.0)  # inside the 90s cli lease if renewed each time
        hub_display.register_client(conn)  # a bare contact renews the lease
        assert hub_display.reap_lapsed_leases() == frozenset()

    assert [menu.label for menu in registry.menu_bar()] == ["Tools"]
    assert marker.menu_marks == 0  # a renewed owner is never swept, so never re-marked
