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

from punt_lux.domain.hub import client_registry, hub
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.departure_cascade import DepartureCascade
from punt_lux.domain.hub.departure_sinks import DepartureSink
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, inbox_depth_for, next_event
from punt_lux.domain.hub.lease_reap_sweep import LeaseReapSweep
from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations import Operations
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.ports import HubPorts
from punt_lux.operations.scope import Scope

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
) -> tuple[Operations, HubDisplay, _MarkerSpy]:
    store, spy = HubDisplay(clock), _MarkerSpy()
    ops = Operations.for_store(
        store,
        spy,
        hub=hub,
        menu_registry=HubMenuRegistry(store.clients),
        callback_router=CallbackRouter(store.clients),
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
    return ops, store, spy


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
    ops, _store, spy = _rig()

    ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks >= 1
    assert _sent_entries(ops) == ["claude"]


def test_re_identifying_marks_menus_again() -> None:
    ops, _store, spy = _rig()
    ops.identify(_AGENT, scope=Scope(_CONN))
    before = spy.menu_marks

    ops.identify({**_AGENT, "repo": "/w/other"}, scope=Scope(_CONN))

    assert spy.menu_marks > before


def test_its_departure_marks_menus_and_the_entry_is_gone() -> None:
    ops, store, spy = _rig()
    ops.identify(_AGENT, scope=Scope(_CONN))
    before = spy.menu_marks

    store.drop_connection(_CONN)

    assert spy.menu_marks > before
    assert _sent_entries(ops) == []


def test_a_lease_lapse_reap_marks_menus_and_the_entry_is_gone() -> None:
    """The timer's own sweep -- no disconnect signal -- withdraws the entry."""
    now = [0.0]
    ops, store, spy = _rig(lambda: now[0])
    ops.identify(_AGENT, scope=Scope(_CONN))
    before = spy.menu_marks

    now[0] += 1_000_000.0  # far past any kind's lease; nothing renews
    reaped = LeaseReapSweep(store).sweep()

    assert reaped == frozenset({_CONN})
    assert spy.menu_marks > before
    assert _sent_entries(ops) == []


def test_repeating_an_identical_identify_marks_menus_once() -> None:
    """REST re-declares identity on every write; that must not re-push the menu."""
    ops, _store, spy = _rig()
    ops.identify(_AGENT, scope=Scope(_CONN))
    after_first = spy.menu_marks

    for _ in range(3):
        ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks == after_first


def test_a_departure_cannot_interleave_with_binding_the_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record and the bind are one step under the store's write lock."""
    ops, store, _spy = _rig()
    ops.identify(_AGENT, scope=Scope(_CONN))
    real_bind = DepartureCascade.bind_sink
    intruder = threading.Thread(target=store.drop_connection, args=(_CONN,))
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


def _departure_marks(store: HubDisplay, spy: _MarkerSpy, conn: ConnectionId) -> int:
    """How many menu marks one departure of ``conn`` raises: the sinks it fires."""
    before = spy.menu_marks
    store.drop_connection(conn)
    return spy.menu_marks - before


def test_identifying_an_anonymous_registered_connection_as_an_agent_marks_menus_and_binds_one_sink() -> (  # noqa: E501
    None
):
    ops, store, spy = _rig()
    store.register_client(_CONN)  # registered, anonymous: the Connect step first
    assert spy.menu_marks == 0

    ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks >= 1
    assert _sent_entries(ops) == ["claude"]
    assert _departure_marks(store, spy, _CONN) == 1


def test_a_cli_identify_marks_nothing_and_binds_no_sink() -> None:
    """A cli earns no Clients entry, so naming it owes the Display nothing."""
    ops, store, spy = _rig()

    ops.identify(_CLI, scope=Scope(_CONN))

    assert spy.menu_marks == 0
    assert _departure_marks(store, spy, _CONN) == 0


def test_identify_binds_exactly_one_menu_sink() -> None:
    ops, store, spy = _rig()

    for _ in range(3):
        ops.identify(_AGENT, scope=Scope(_CONN))

    assert _departure_marks(store, spy, _CONN) == 1


def test_a_departure_between_the_before_snapshot_and_the_record_still_marks_and_binds() -> (  # noqa: E501
    None
):
    """A departure landing just before the record leaves no ghost (D5).

    The intruder drops the connection as the record begins, so the identify that
    follows re-registers a session the departure already took. The end state
    must be the same as a first identify: marked, listed, one sink bound, and a
    later departure marks the entry away.
    """
    ops, store, spy = _rig()
    ops.identify(_AGENT, scope=Scope(_CONN))
    real_identify = store.identify_client
    marks_after_intrusion: list[int] = []

    def _intruded(connection_id: ConnectionId, identity: ClientIdentity) -> None:
        store.drop_connection(connection_id)
        marks_after_intrusion.append(spy.menu_marks)
        real_identify(connection_id, identity)

    store.identify_client = _intruded  # type: ignore[method-assign]  # spy
    ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks > marks_after_intrusion[0]
    assert _sent_entries(ops) == ["claude"]
    assert _departure_marks(store, spy, _CONN) == 1
    assert _sent_entries(ops) == []


def test_a_lease_lapse_alone_marks_nothing() -> None:
    """A lapse is time passing, not a Hub event: it cannot mark."""
    now = [0.0]
    ops, _store, spy = _rig(lambda: now[0])
    ops.identify(_AGENT, scope=Scope(_CONN))
    before = spy.menu_marks

    now[0] += _FAR_FUTURE

    assert spy.menu_marks == before


def test_another_clients_push_drops_a_lapsed_unswept_agent() -> None:
    """The roster is lease-filtered, so a push omits the lapsed agent unswept."""
    now = [0.0]
    ops, store, _spy = _rig(lambda: now[0])
    ops.identify(_AGENT, scope=Scope(_CONN))

    now[0] += _FAR_FUTURE

    assert store.is_client(_CONN)  # no sweep has run
    assert _sent_entries(ops) == []


def test_a_rest_write_renewing_a_lapsed_agent_marks_menus_and_restores_its_entry() -> (
    None
):
    now = [0.0]
    ops, _store, spy = _rig(lambda: now[0])
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
    ops, _store, spy = _rig(lambda: now[0])
    ops.identify(_AGENT, scope=Scope(_CONN))
    now[0] += _FAR_FUTURE
    before = spy.menu_marks

    ops.identify(_AGENT, scope=Scope(_CONN))

    assert spy.menu_marks > before
    assert _sent_entries(ops) == ["claude"]


def test_renewing_a_lapsed_agent_leaves_exactly_one_menu_sink() -> None:
    now = [0.0]
    ops, store, spy = _rig(lambda: now[0])
    ops.identify(_AGENT, scope=Scope(_CONN))
    now[0] += _FAR_FUTURE
    ops.clear(scope=Scope(_CONN))

    assert _departure_marks(store, spy, _CONN) == 1


def test_the_sweep_removes_every_lapsed_agent_with_a_mark() -> None:
    now = [0.0]
    ops, store, spy = _rig(lambda: now[0])
    other = ConnectionId("c2")
    ops.identify(_AGENT, scope=Scope(_CONN))
    ops.identify({**_AGENT, "name": "codex"}, scope=Scope(other))
    before = spy.menu_marks
    now[0] += _FAR_FUTURE

    reaped = LeaseReapSweep(store).sweep()

    assert reaped == frozenset({_CONN, other})
    assert spy.menu_marks > before
    assert _sent_entries(ops) == []


def test_a_non_agent_departure_marks_nothing() -> None:
    ops, store, spy = _rig()
    ops.identify(_CLI, scope=Scope(_CONN))
    store.register_client(ConnectionId("anon"))

    assert _departure_marks(store, spy, ConnectionId("anon")) == 0
    assert _departure_marks(store, spy, _CONN) == 0
