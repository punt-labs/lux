"""Identifying and departing change who the Clients menu lists.

A connection with no callbacks has no other event that would tell the Display it
arrived or left, so naming it marks the menu for re-push and its departure does
the same. Driven through the real facade, so the wiring is what is under test.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Self, final

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub import client_registry, hub
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
from punt_lux.domain.hub.departure_cascade import DepartureCascade
from punt_lux.domain.hub.departure_sinks import DepartureSink
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.inbox import ensure_writer, inbox_depth_for, next_event
from punt_lux.domain.hub.lease_reap_sweep import LeaseReapSweep
from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.scope import Scope
from punt_lux.operations import Operations
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.ports import HubPorts

if TYPE_CHECKING:
    import pytest

_AGENT: dict[str, object] = {"kind": "mcp-session", "name": "claude", "repo": "/w/lux"}
_CONN = ConnectionId("c1")


@final
class _MarkerSpy:
    """A DirtyMarker counting menu pushes."""

    _menus: int
    __slots__ = ("_menus",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._menus = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        msg = f"identifying must not mark scene {scene_id!r} dirty"
        raise AssertionError(msg)

    def mark_menus(self) -> None:
        self._menus += 1

    @property
    def disconnected_delay(self) -> float:
        return 0.0

    @property
    def menu_marks(self) -> int:
        return self._menus


def _rig(
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Operations, HubStoreFactory, _MarkerSpy]:
    factory = HubStoreFactory(clock=clock)
    store = factory.display
    lifecycle = factory.lifecycle
    clients = factory.clients
    spy = _MarkerSpy()
    ops = Operations.for_store(
        store,
        spy,
        lifecycle=lifecycle,
        clients=clients,
        hub=hub,
        menu_registry=HubMenuRegistry(clients),
        callback_router=CallbackRouter(clients),
        callback_menus=CallbackMenuReplica(clients),
        ports=HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=ensure_writer,
            next_event=next_event,
            inbox_depth=inbox_depth_for,
            display_port=HubDisplayConnection(
                is_running=lambda: False, clients=client_registry
            ),
        ),
    )
    return ops, factory, spy


def _sent_entries(ops: Operations) -> list[str]:
    """The labels under every Clients submenu, as the replicator would send them."""
    return [
        entry.label
        for menu in ops.list_menus().menus
        for submenu in menu.items
        if isinstance(submenu, Menu)
        for entry in submenu.items
        if isinstance(entry, MenuAction)
    ]


def test_identifying_a_callbackless_agent_marks_menus_and_it_is_listed() -> None:
    ops, _factory, spy = _rig()

    ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks >= 1
    assert _sent_entries(ops) == ["claude"]


def test_re_identifying_marks_menus_again() -> None:
    ops, _factory, spy = _rig()
    ops.identify(_AGENT, scope=Scope(_CONN))
    before = spy.menu_marks

    ops.identify({**_AGENT, "repo": "/w/other"}, scope=Scope(_CONN))

    assert spy.menu_marks > before


def test_its_departure_marks_menus_and_the_entry_is_gone() -> None:
    ops, factory, spy = _rig()
    lifecycle = factory.lifecycle
    ops.identify(_AGENT, scope=Scope(_CONN))
    before = spy.menu_marks

    lifecycle.depart(_CONN)

    assert spy.menu_marks > before
    assert _sent_entries(ops) == []


def test_a_lease_lapse_reap_marks_menus_and_the_entry_is_gone() -> None:
    """The timer's own sweep -- no disconnect signal -- withdraws the entry."""
    now = [0.0]
    ops, factory, spy = _rig(lambda: now[0])
    lifecycle = factory.lifecycle
    ops.identify(_AGENT, scope=Scope(_CONN))
    before = spy.menu_marks

    now[0] += 1_000_000.0  # far past any kind's lease; nothing renews
    reaped = LeaseReapSweep(lifecycle).sweep()

    assert reaped == frozenset({_CONN})
    assert spy.menu_marks > before
    assert _sent_entries(ops) == []


def test_repeating_an_identical_identify_marks_menus_once() -> None:
    """REST re-declares identity on every write; that must not re-push the menu."""
    ops, _factory, spy = _rig()
    ops.identify(_AGENT, scope=Scope(_CONN))
    after_first = spy.menu_marks

    for _ in range(3):
        ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks == after_first


def test_a_departure_cannot_interleave_with_binding_the_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record and the bind are one step under the store's write lock."""
    ops, factory, _spy = _rig()
    lifecycle = factory.lifecycle
    ops.identify(_AGENT, scope=Scope(_CONN))
    real_bind = DepartureCascade.bind_sink
    intruder = threading.Thread(target=lifecycle.depart, args=(_CONN,))
    overlapped: list[bool] = []

    def _bind(
        self: DepartureCascade, connection_id: ConnectionId, sink: DepartureSink
    ) -> None:
        if not intruder.is_alive() and not overlapped:
            intruder.start()
            intruder.join(timeout=0.3)
            overlapped.append(not intruder.is_alive())
        real_bind(self, connection_id, sink)

    monkeypatch.setattr(DepartureCascade, "bind_sink", _bind)
    ops.identify({**_AGENT, "repo": "/w/other"}, scope=Scope(_CONN))
    intruder.join(timeout=2.0)

    assert overlapped == [False]


_CLI: dict[str, object] = {"kind": "cli", "name": "tool", "repo": "/w/lux"}
_FAR_FUTURE = 1_000_000.0  # past any kind's lease; nothing renews


def _departure_marks(
    lifecycle: ClientLifecycle, spy: _MarkerSpy, conn: ConnectionId
) -> int:
    """How many menu marks one departure of ``conn`` raises: the sinks it fires."""
    before = spy.menu_marks
    lifecycle.depart(conn)
    return spy.menu_marks - before


def test_identifying_an_anonymous_registered_connection_as_an_agent_marks_menus_and_binds_one_sink() -> (  # noqa: E501
    None
):
    ops, factory, spy = _rig()
    lifecycle = factory.lifecycle
    lifecycle.arrive(_CONN, UNOBSERVED)  # registered, anonymous: the Connect step first
    assert spy.menu_marks == 0

    ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks >= 1
    assert _sent_entries(ops) == ["claude"]
    assert _departure_marks(lifecycle, spy, _CONN) == 1


def test_a_cli_identify_marks_nothing_and_binds_no_sink() -> None:
    """A cli earns no Clients entry, so naming it owes the Display nothing."""
    ops, factory, spy = _rig()
    lifecycle = factory.lifecycle

    ops.identify(_CLI, scope=Scope(_CONN))

    assert spy.menu_marks == 0
    assert _departure_marks(lifecycle, spy, _CONN) == 0


def test_identify_binds_exactly_one_menu_sink() -> None:
    ops, factory, spy = _rig()
    lifecycle = factory.lifecycle

    for _ in range(3):
        ops.identify(_AGENT, scope=Scope(_CONN))

    assert _departure_marks(lifecycle, spy, _CONN) == 1


def test_a_departure_landing_before_the_record_still_marks_and_binds() -> None:
    """A departure landing just before the record leaves no ghost (D5).

    The test thread holds the store lock through the door's own ``exclusive()``,
    so an identify on a worker thread queues behind it; the departure lands inside
    that hold, and the identify then runs wholly after it. The session the
    departure took is re-registered by the identify, and the end state must be the
    same as a first identify: marked, listed, one sink bound, and a later departure
    marks the entry away.
    """
    ops, factory, spy = _rig()
    lifecycle = factory.lifecycle
    ops.identify(_AGENT, scope=Scope(_CONN))
    worker = threading.Thread(
        target=ops.identify, args=(_AGENT,), kwargs={"scope": Scope(_CONN)}
    )

    with lifecycle.exclusive():
        worker.start()
        lifecycle.depart(_CONN)
        marks_after_departure = spy.menu_marks
    worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert spy.menu_marks > marks_after_departure
    assert _sent_entries(ops) == ["claude"]
    assert _departure_marks(lifecycle, spy, _CONN) == 1
    assert _sent_entries(ops) == []


def test_a_lease_lapse_alone_marks_nothing() -> None:
    """A lapse is time passing, not a Hub event: it cannot mark."""
    now = [0.0]
    ops, _factory, spy = _rig(lambda: now[0])
    ops.identify(_AGENT, scope=Scope(_CONN))
    before = spy.menu_marks

    now[0] += _FAR_FUTURE

    assert spy.menu_marks == before


def test_another_clients_push_drops_a_lapsed_unswept_agent() -> None:
    """The roster is lease-filtered, so a push omits the lapsed agent unswept."""
    now = [0.0]
    ops, factory, _spy = _rig(lambda: now[0])
    clients = factory.clients
    ops.identify(_AGENT, scope=Scope(_CONN))

    now[0] += _FAR_FUTURE

    assert clients.session_of(_CONN) is not None  # no sweep has run
    assert _sent_entries(ops) == []


def test_a_rest_write_renewing_a_lapsed_agent_marks_menus_and_restores_its_entry() -> (
    None
):
    now = [0.0]
    ops, _factory, spy = _rig(lambda: now[0])
    ops.identify(_AGENT, scope=Scope(_CONN))
    now[0] += _FAR_FUTURE
    before = spy.menu_marks

    ops.clear(scope=Scope(_CONN))  # a write: the lease renews on contact

    assert spy.menu_marks > before
    assert _sent_entries(ops) == ["claude"]


def test_an_mcp_call_renewing_a_lapsed_agent_marks_menus_and_restores_its_entry() -> (
    None
):
    """The D4 test: an identify with an unchanged identity must still mark."""
    now = [0.0]
    ops, _factory, spy = _rig(lambda: now[0])
    ops.identify(_AGENT, scope=Scope(_CONN))
    now[0] += _FAR_FUTURE
    before = spy.menu_marks

    ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks > before
    assert _sent_entries(ops) == ["claude"]


def test_renewing_a_lapsed_agent_leaves_exactly_one_menu_sink() -> None:
    now = [0.0]
    ops, factory, spy = _rig(lambda: now[0])
    lifecycle = factory.lifecycle
    ops.identify(_AGENT, scope=Scope(_CONN))
    now[0] += _FAR_FUTURE
    ops.clear(scope=Scope(_CONN))

    assert _departure_marks(lifecycle, spy, _CONN) == 1


def test_the_sweep_removes_every_lapsed_agent_with_a_mark() -> None:
    now = [0.0]
    ops, factory, spy = _rig(lambda: now[0])
    lifecycle = factory.lifecycle
    other = ConnectionId("c2")
    ops.identify(_AGENT, scope=Scope(_CONN))
    ops.identify({**_AGENT, "name": "codex"}, scope=Scope(other))
    before = spy.menu_marks
    now[0] += _FAR_FUTURE

    reaped = LeaseReapSweep(lifecycle).sweep()

    assert reaped == frozenset({_CONN, other})
    assert spy.menu_marks > before
    assert _sent_entries(ops) == []


def test_a_non_agent_departure_marks_nothing() -> None:
    ops, factory, spy = _rig()
    lifecycle = factory.lifecycle
    ops.identify(_CLI, scope=Scope(_CONN))
    lifecycle.arrive(ConnectionId("anon"), UNOBSERVED)

    assert _departure_marks(lifecycle, spy, ConnectionId("anon")) == 0
    assert _departure_marks(lifecycle, spy, _CONN) == 0
