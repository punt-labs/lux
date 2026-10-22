"""Identifying and departing change who the Clients menu lists.

A connection with no callbacks has no other event that would tell the Display it
arrived or left, so naming it marks the menu for re-push and its departure does
the same. Driven through the real facade, so the wiring is what is under test.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub import client_registry, hub
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, inbox_depth_for, next_event
from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations import Operations
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.ports import HubPorts
from punt_lux.operations.scope import Scope

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


def _rig() -> tuple[Operations, HubDisplay, _MarkerSpy]:
    store, spy = HubDisplay(), _MarkerSpy()
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
