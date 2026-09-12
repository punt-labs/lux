"""D2: a menu owner's lease-lapse departure withdraws its bar from the registry.

The Hub owns the agent menu bar keyed by the owning session (MO: ``menuOwner ⊆
registered``, modelled in ``docs/menu_lifecycle.tex``). Before the fix, only the
graceful ``session_cleanup`` leg pruned a departed owner's bar; a lease-lapse
departure (the timer's own sweep) left the registry entry standing, so a
``menuOwner`` outlived its ``registered`` session. The fix binds
``HubMenuRegistry.drop_session`` as a departure sink at the ``menu_set`` admit
moment, so EVERY departure trigger prunes the bar -- exercised here through the
real :class:`MenuArming` admit path, not a hand-bound sink.
"""

from __future__ import annotations

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.menu_models import Menu
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.menu_arming import MenuArming


class _Clock:
    """A hand-advanced monotonic clock, so lease expiry is deterministic."""

    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _cli(name: str) -> ClientIdentity:
    """A ``cli``-kind identity — the 90s lease the reaping tests advance past."""
    return ClientIdentity(kind="cli", name=name, repo="/w/lux")


def _armed(hub_display: HubDisplay, registry: HubMenuRegistry) -> MenuArming:
    """MenuArming wired exactly as ``facade.for_store`` wires it, over a test store.

    The third argument — the departure arm — binds the registry prune as a
    departure sink, the production behaviour under test here.
    """
    return MenuArming(
        hub_display.clients,
        lambda _cid: None,  # ensure_writer: incidental to the departure leg
        lambda cid: hub_display.bind_departure_sink(cid, registry.drop_session),
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
    arming = _armed(hub_display, registry)

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


def test_a_renewing_menu_owner_keeps_its_bar_across_reap_opportunities() -> None:
    """D2 companion: an owner that keeps renewing is never swept, so its bar stands."""
    clock = _Clock()
    hub_display = HubDisplay(clock)
    registry = HubMenuRegistry(hub_display.clients)
    arming = _armed(hub_display, registry)

    conn = ConnectionId("steady")
    hub_display.identify_client(conn, _cli("steady"))
    registry.set_menus(conn, [Menu(label="Tools", items=[])])
    assert arming.admit(conn) is True

    for _ in range(3):
        clock.advance(60.0)  # inside the 90s cli lease if renewed each time
        hub_display.register_client(conn)  # a bare contact renews the lease
        assert hub_display.reap_lapsed_leases() == frozenset()

    assert [menu.label for menu in registry.menu_bar()] == ["Tools"]
