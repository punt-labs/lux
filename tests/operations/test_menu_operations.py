"""MenuOperations — the agent menu bar is Hub-owned; the replicator pushes it.

set_menu admits an identified session, keys the bar under it, and hands the
composed bar to the replicator (the sole writer), never reaching the display
directly. A spy replicator records the marks, proving there is no second writer.
list_menus reads the live registry and round-trips the separator sentinel through
the typed model, then appends the Clients menu.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager, nullcontext
from typing import Self, final

import pytest
from pydantic import ValidationError

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.menu_models import Menu, MenuAction, MenuSeparator
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.menu_arming import MenuArming
from punt_lux.operations.menus import MenuOperations, MenuOperationsDeps
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import MenuList, Ok, SetMenuRequest
from punt_lux.operations.scope import Scope


@final
class _CallbackMenus:
    """A CallbackMenuSource returning fixed submenus — the callback model's side."""

    _menus: list[Menu]

    def __new__(cls, menus: Sequence[Menu] = ()) -> Self:
        self = super().__new__(cls)
        self._menus = list(menus)
        return self

    def callback_menus(self) -> list[Menu]:
        return list(self._menus)


class _MenuMarkerSpy:
    """A DirtyMarker counting the payload-less menu flags — nothing else touched."""

    _flags: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._flags = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError("a menu write must not mark a scene dirty")

    def mark_menus(self) -> None:
        self._flags += 1

    @property
    def pushed(self) -> int:
        """How many times a menu push was flagged."""
        return self._flags


@final
class _Ops:
    """A MenuOperations wired over a real client registry, for these tests."""

    ops: MenuOperations
    marker: _MenuMarkerSpy
    registry: HubMenuRegistry
    clients: HubClientRegistry
    __slots__ = ("clients", "marker", "ops", "registry")

    def __new__(cls, callback_menus: Sequence[Menu] = ()) -> Self:
        self = super().__new__(cls)
        self.clients = HubClientRegistry()
        self.marker = _MenuMarkerSpy()
        self.registry = HubMenuRegistry(self.clients)
        arming = MenuArming(self.clients, lambda _cid: None, lambda _cid: None)
        self.ops = MenuOperations(
            MenuOperationsDeps(
                registry=self.registry,
                replicator=self.marker,
                callback_menus=_CallbackMenus(callback_menus),
                arming=arming,
                write_lock=lambda: nullcontext(True),
            )
        )
        return self

    def identified(self, name: str = "sess") -> Scope:
        """Register an identified, live session and return its scope."""
        conn = ConnectionId(name)
        self.clients.record(conn, ClientIdentity(kind="mcp-session", name="agent"))
        return Scope(conn)


def test_set_menu_writes_the_registry_and_pushes_via_the_replicator() -> None:
    ctx = _Ops()
    scope = ctx.identified()

    request = SetMenuRequest.parse(
        [{"label": "File", "items": [{"label": "Run", "id": "run"}]}]
    )
    result = ctx.ops.set_menu(request, scope=scope)

    assert isinstance(result, Ok)
    # The agent bar landed in the registry as a typed model, and exactly one push
    # was marked — the replicator is the only writer.
    assert any(m.label == "File" for m in ctx.registry.menu_bar())
    assert ctx.marker.pushed == 1


def test_set_menu_refuses_an_anonymous_session() -> None:
    # Nothing anonymous owns a menu item — the same gate the callback path enforces.
    ctx = _Ops()
    anon = Scope(ConnectionId("anon"))  # never identified

    result = ctx.ops.set_menu(
        SetMenuRequest.parse([{"label": "File", "items": []}]), scope=anon
    )

    assert isinstance(result, OpError)
    assert result.code == "identification_required"
    assert ctx.marker.pushed == 0


def test_set_menu_rejects_a_menu_with_a_missing_label() -> None:
    # A menu with no label is rejected by name, not coerced to a blank bar entry.
    result = SetMenuRequest.parse([{"items": [{"label": "Run", "id": "run"}]}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.label" in result.reason


def test_set_menu_rejects_a_menu_with_an_empty_label() -> None:
    result = SetMenuRequest.parse([{"label": "", "items": []}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.label" in result.reason


def test_menu_rejects_direct_construction_with_a_blank_label() -> None:
    # The model itself forbids a blank label; from_wire is not the only guard.
    with pytest.raises(ValidationError):
        Menu(label="", items=[])


def test_set_menu_rejects_a_menu_whose_items_is_not_a_list() -> None:
    # A present-but-non-list items value is rejected by name, not coerced to [].
    result = SetMenuRequest.parse([{"label": "File", "items": 123}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items" in result.reason


def test_set_menu_rejects_a_menu_whose_items_is_a_string() -> None:
    # A string is a Sequence but never a menu item list — reject, do not iterate it.
    result = SetMenuRequest.parse([{"label": "File", "items": "oops"}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items" in result.reason


def test_set_menu_accepts_a_menu_with_no_items_key() -> None:
    # A missing items key is the one absence that defaults to an empty menu.
    result = SetMenuRequest.parse([{"label": "File"}])
    assert isinstance(result, SetMenuRequest)
    assert result.menus[0].items == []


def test_set_menu_rejects_an_action_item_with_a_missing_label() -> None:
    # An id present but no label is a half-formed action, not a blank menu item.
    result = SetMenuRequest.parse([{"label": "File", "items": [{"id": "run"}]}])
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.label" in result.reason


def test_set_menu_rejects_an_action_item_with_a_non_string_label() -> None:
    result = SetMenuRequest.parse(
        [{"label": "File", "items": [{"id": "run", "label": 123}]}]
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.label" in result.reason


def test_set_menu_rejects_an_action_item_with_a_non_string_id() -> None:
    result = SetMenuRequest.parse(
        [{"label": "File", "items": [{"id": 7, "label": "Run"}]}]
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.id" in result.reason


def test_set_menu_rejects_an_id_carrying_the_leaf_separator() -> None:
    # A stamped leaf id splits on the unit separator; an agent id must not carry it.
    result = SetMenuRequest.parse(
        [{"label": "File", "items": [{"id": "a\x1fb", "label": "Run"}]}]
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.id" in result.reason


def test_set_menu_rejects_a_frame_id_carrying_the_leaf_separator() -> None:
    # A frame_id names a leaf key too, so the same non-blank, separator-free rule
    # the id gets applies at the agent boundary — rejected by field path.
    result = SetMenuRequest.parse(
        [
            {
                "label": "File",
                "items": [{"id": "run", "label": "Run", "frame_id": "a\x1fb"}],
            }
        ]
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.frame_id" in result.reason


def test_set_menu_rejects_a_blank_frame_id() -> None:
    result = SetMenuRequest.parse(
        [{"label": "File", "items": [{"id": "run", "label": "Run", "frame_id": ""}]}]
    )
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert "menus.0.items.0.frame_id" in result.reason


def test_list_menus_round_trips_the_separator_sentinel() -> None:
    ctx = _Ops()
    scope = ctx.identified()
    ctx.ops.set_menu(
        SetMenuRequest.parse(
            [
                {
                    "label": "File",
                    "items": [{"label": "Open", "id": "open"}, {"label": "---"}],
                }
            ]
        ),
        scope=scope,
    )

    result = ctx.ops.list_menus()

    assert isinstance(result, MenuList)
    menu = next(m for m in result.menus if m.label == "File")
    # The "---" wire sentinel decodes to a typed separator, never a magic label.
    assert isinstance(menu.items[1], MenuSeparator)


def test_list_menus_appends_the_callback_submenus_after_the_agent_bar() -> None:
    # The read reports both parts side by side: the agent bar first, then the
    # Clients menu the callback model contributes.
    callback_submenu = Menu(label="vox", items=[MenuAction(id="c", label="Beads")])
    ctx = _Ops([callback_submenu])
    scope = ctx.identified()
    ctx.ops.set_menu(
        SetMenuRequest.parse([{"label": "File", "items": []}]), scope=scope
    )

    labels = [menu.label for menu in ctx.ops.list_menus().menus]
    assert labels == ["File", "vox"]


def test_list_menus_keeps_an_action_labelled_like_the_separator() -> None:
    # An action carrying an id survives round-trip as an action even when its
    # label is the "---" sentinel — discrimination is on the id, not the label.
    ctx = _Ops()
    scope = ctx.identified()
    ctx.ops.set_menu(
        SetMenuRequest.parse(
            [{"label": "Edit", "items": [{"label": "---", "id": "dash"}]}]
        ),
        scope=scope,
    )

    menu = next(m for m in ctx.ops.list_menus().menus if m.label == "Edit")
    assert isinstance(menu.items[0], MenuAction)
    assert menu.items[0].id == "dash"


# -- D3: set_menu holds the write lock across admit AND store -----------------


@final
class _RecordingMarker:
    """A DirtyMarker that logs its menu push into a shared ordering list."""

    _events: list[str]
    __slots__ = ("_events",)

    def __new__(cls, events: list[str]) -> Self:
        self = super().__new__(cls)
        self._events = events
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError("a menu write must not mark a scene dirty")

    def mark_menus(self) -> None:
        self._events.append("push")


@final
class _WriteLockSpy:
    """A reentrant write-lock stand-in logging enter/exit into a shared list."""

    _events: list[str]
    _depth: int
    __slots__ = ("_depth", "_events")

    def __new__(cls, events: list[str]) -> Self:
        self = super().__new__(cls)
        self._events = events
        self._depth = 0
        return self

    @contextmanager
    def __call__(self) -> Generator[bool]:
        # Reentrant, like the real StoreLock: only the outermost enter/exit is
        # logged, so a nested admit->ensure_writer hold does not add noise.
        outer = self._depth == 0
        self._depth += 1
        if outer:
            self._events.append("enter")
        try:
            yield True
        finally:
            self._depth -= 1
            if outer:
                self._events.append("exit")


def test_set_menu_holds_the_write_lock_across_admit_and_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3: the admit-liveness gate AND the registry store both run under one hold.

    Records the interleaving of the write lock's enter/exit against admit and
    set_menus. The store must land inside the hold so a departure cannot slip
    between the gate and the write (MO, modelled in ``docs/menu_lifecycle.tex``);
    the push must land after release. Fail-on-current if the store moves outside
    the ``with`` (``enter, admit, exit, set_menus``) or the push moves inside it.
    """
    events: list[str] = []
    clients = HubClientRegistry()
    registry = HubMenuRegistry(clients)
    arming = MenuArming(clients, lambda _cid: None, lambda _cid: None)

    original_admit = MenuArming.admit
    original_set_menus = HubMenuRegistry.set_menus

    def _rec_admit(self: MenuArming, connection_id: ConnectionId) -> bool:
        events.append("admit")
        return original_admit(self, connection_id)

    def _rec_set_menus(
        self: HubMenuRegistry,
        connection_id: ConnectionId,
        menus: Sequence[Menu],
    ) -> None:
        events.append("set_menus")
        original_set_menus(self, connection_id, menus)

    monkeypatch.setattr(MenuArming, "admit", _rec_admit)
    monkeypatch.setattr(HubMenuRegistry, "set_menus", _rec_set_menus)

    ops = MenuOperations(
        MenuOperationsDeps(
            registry=registry,
            replicator=_RecordingMarker(events),
            callback_menus=_CallbackMenus(),
            arming=arming,
            write_lock=_WriteLockSpy(events),
        )
    )
    conn = ConnectionId("sess")
    clients.record(conn, ClientIdentity(kind="mcp-session", name="agent"))

    result = ops.set_menu(
        SetMenuRequest.parse([{"label": "File", "items": []}]), scope=Scope(conn)
    )

    assert isinstance(result, Ok)
    assert events == ["enter", "admit", "set_menus", "exit", "push"]


def test_set_menu_does_not_store_when_admit_refuses_under_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3 negative: an anonymous session is refused inside the hold, storing nothing.

    The gate runs under the lock and returns before any store, so the lock is
    entered and exited with no ``set_menus`` and no push between.
    """
    events: list[str] = []
    clients = HubClientRegistry()
    registry = HubMenuRegistry(clients)
    arming = MenuArming(clients, lambda _cid: None, lambda _cid: None)

    original_set_menus = HubMenuRegistry.set_menus

    def _rec_set_menus(
        self: HubMenuRegistry,
        connection_id: ConnectionId,
        menus: Sequence[Menu],
    ) -> None:
        events.append("set_menus")
        original_set_menus(self, connection_id, menus)

    monkeypatch.setattr(HubMenuRegistry, "set_menus", _rec_set_menus)

    ops = MenuOperations(
        MenuOperationsDeps(
            registry=registry,
            replicator=_RecordingMarker(events),
            callback_menus=_CallbackMenus(),
            arming=arming,
            write_lock=_WriteLockSpy(events),
        )
    )
    anon = Scope(ConnectionId("anon"))  # never identified

    result = ops.set_menu(
        SetMenuRequest.parse([{"label": "File", "items": []}]), scope=anon
    )

    assert isinstance(result, OpError)
    assert events == ["enter", "exit"]
