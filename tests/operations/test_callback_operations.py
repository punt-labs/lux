"""CallbackOperations — register callbacks, route their clicks, read the menu.

Registration is a write only an identified session may make (the identify
challenge otherwise), and a registration that took pushes the menu. A click's
leaf id routes to the owning session's bounded hold; a click for a departed
session or an unregistered callback is not_found, and a malformed leaf id is
invalid_request. The menu build is the uniform session-then-callback tree.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.callbacks import CallbackOperations
from punt_lux.operations.models.callbacks import RegisterCallbackRequest
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import Ok
from punt_lux.operations.scope import Scope


@final
class _Clock:
    """A hand-advanced clock so a session's lease lapses deterministically."""

    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@final
class _MarkerSpy:
    """A DirtyMarker counting menu pushes; a scene mark would be the wrong writer."""

    _flags: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._flags = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError("registering a callback must not mark a scene dirty")

    def mark_menus(self) -> None:
        self._flags += 1

    @property
    def pushed(self) -> int:
        return self._flags


def _identity(name: str = "claude", repo: str = "/w/lux") -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name=name, repo=repo)


def _ops(
    clients: HubClientRegistry, marker: _MarkerSpy, *, capacity: int = 32
) -> CallbackOperations:
    return CallbackOperations(clients, CallbackRouter(clients, capacity), marker)


def _register(
    ops: CallbackOperations, conn: ConnectionId, callback_id: str
) -> Ok | OpError:
    request = RegisterCallbackRequest.parse(callback_id=callback_id, label="Beads")
    return ops.register_callback(request, scope=Scope(conn))


def test_registration_requires_an_identified_session() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("bare")
    clients.record(conn)  # bound, but never declared an identity
    marker = _MarkerSpy()
    result = _register(_ops(clients, marker), conn, "beads")
    assert isinstance(result, OpError)
    assert result.code == "identification_required"
    assert marker.pushed == 0  # nothing registered, nothing pushed


def test_an_identified_session_registers_and_the_menu_is_pushed() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("mcp")
    clients.record(conn, _identity())
    marker = _MarkerSpy()
    ops = _ops(clients, marker)

    assert isinstance(_register(ops, conn, "beads"), Ok)
    assert marker.pushed == 1
    menus = ops.callback_menus()
    assert len(menus) == 1
    assert menus[0].label == "claude — /w/lux"


def test_a_malformed_request_passes_through_without_pushing() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("mcp")
    clients.record(conn, _identity())
    marker = _MarkerSpy()
    result = _register(_ops(clients, marker), conn, "")  # empty id
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert marker.pushed == 0


def test_a_click_routes_to_the_owning_session_and_is_held() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("mcp")
    clients.record(conn, _identity())
    ops = _ops(clients, _MarkerSpy())
    _register(ops, conn, "beads")

    menu_id = CallbackInvocation(conn, "beads").menu_id
    assert isinstance(ops.invoke_callback(menu_id), Ok)
    assert ops.pending_callbacks(conn).callback_ids == ("beads",)


def test_the_hold_is_bounded() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("mcp")
    clients.record(conn, _identity())
    ops = _ops(clients, _MarkerSpy(), capacity=2)
    _register(ops, conn, "beads")

    menu_id = CallbackInvocation(conn, "beads").menu_id
    for _ in range(5):
        ops.invoke_callback(menu_id)
    assert ops.pending_callbacks(conn).callback_ids == ("beads", "beads")  # capped at 2


def test_a_click_for_a_departed_session_is_not_found() -> None:
    clock = _Clock()
    clients = HubClientRegistry(clock)
    conn = ConnectionId("cli")
    clients.record(conn, ClientIdentity(kind="cli", name="lux", repo="/w/lux"))
    ops = _ops(clients, _MarkerSpy())
    _register(ops, conn, "beads")

    clock.advance(91.0)  # past the 90s cli lease — the session leaves the live set
    result = ops.invoke_callback(CallbackInvocation(conn, "beads").menu_id)
    assert isinstance(result, OpError)
    assert result.code == "not_found"
    assert "gone" in result.reason


def test_a_click_for_an_unregistered_callback_is_not_found() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("mcp")
    clients.record(conn, _identity())
    ops = _ops(clients, _MarkerSpy())
    _register(ops, conn, "beads")

    result = ops.invoke_callback(CallbackInvocation(conn, "other").menu_id)
    assert isinstance(result, OpError)
    assert result.code == "not_found"


def test_a_malformed_leaf_id_is_invalid_request() -> None:
    ops = _ops(HubClientRegistry(), _MarkerSpy())
    result = ops.invoke_callback("no-separator")
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"


def test_pending_is_empty_for_a_session_with_no_clicks() -> None:
    ops = _ops(HubClientRegistry(), _MarkerSpy())
    assert ops.pending_callbacks(ConnectionId("nobody")).callback_ids == ()


def test_take_pending_drains_the_hold_so_a_second_poll_is_empty() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("mcp")
    clients.record(conn, _identity())
    ops = _ops(clients, _MarkerSpy())
    _register(ops, conn, "beads")
    ops.invoke_callback(CallbackInvocation(conn, "beads").menu_id)

    # The poll legs' drain: the first take returns the click, the second is empty.
    assert ops.take_pending(conn).callback_ids == ("beads",)
    assert ops.take_pending(conn).callback_ids == ()


def test_peek_does_not_drain_but_take_does() -> None:
    clients = HubClientRegistry()
    conn = ConnectionId("mcp")
    clients.record(conn, _identity())
    ops = _ops(clients, _MarkerSpy())
    _register(ops, conn, "beads")
    ops.invoke_callback(CallbackInvocation(conn, "beads").menu_id)

    assert ops.pending_callbacks(conn).callback_ids == ("beads",)  # peek keeps it
    assert ops.pending_callbacks(conn).callback_ids == ("beads",)  # still there
    assert ops.take_pending(conn).callback_ids == ("beads",)  # drain
    assert ops.pending_callbacks(conn).callback_ids == ()  # now gone


def test_take_pending_drains_only_the_polling_session() -> None:
    clients = HubClientRegistry()
    vox, lux = ConnectionId("vox"), ConnectionId("lux")
    clients.record(vox, _identity("vox", "/w/vox"))
    clients.record(lux, _identity("lux", "/w/lux"))
    ops = _ops(clients, _MarkerSpy())
    _register(ops, vox, "beads")
    _register(ops, lux, "beads")
    ops.invoke_callback(CallbackInvocation(vox, "beads").menu_id)
    ops.invoke_callback(CallbackInvocation(lux, "beads").menu_id)

    # A session drains only its own hold; the other's stays intact.
    assert ops.take_pending(vox).callback_ids == ("beads",)
    assert ops.pending_callbacks(lux).callback_ids == ("beads",)
