"""CallbackOperations — register menu callbacks, route their clicks, read the menu.

Registration has two preconditions: the connection holds a listen leg (a click is
delivered by push, so a connection with none could never learn of it) and the
session has identified. Either failure is a named refusal that registers nothing
and pushes no menu. A click's leaf id routes to the owning session's bounded hold
and wakes its listener; a click for a departed session or an unregistered callback
is not_found, and a malformed leaf id is invalid_request. The menu build is the
uniform ``Clients`` tree.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.menu_models import Menu
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


@final
class _Listener:
    """A persistent leg's wake, counting the pushes a routed click produced."""

    _woken: int
    __slots__ = ("_woken",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._woken = 0
        return self

    def wake(self) -> None:
        self._woken += 1

    @property
    def woken(self) -> int:
        return self._woken


@final
class _Wired:
    """The operations under test with the collaborators a case needs to drive.

    Sessions are made push-reachable through :meth:`connect`, which does what a
    live WebSocket does on accept: record the session's identity and register its
    listener. Nothing else in these tests may register a callback.
    """

    _clients: HubClientRegistry
    _router: CallbackRouter
    _marker: _MarkerSpy
    _ops: CallbackOperations
    __slots__ = ("_clients", "_marker", "_ops", "_router")

    def __new__(cls, *, clock: _Clock | None = None, capacity: int = 32) -> Self:
        self = super().__new__(cls)
        self._clients = (
            HubClientRegistry(clock) if clock is not None else HubClientRegistry()
        )
        self._router = CallbackRouter(self._clients, capacity)
        self._marker = _MarkerSpy()
        self._ops = CallbackOperations(self._clients, self._router, self._marker)
        return self

    @property
    def ops(self) -> CallbackOperations:
        return self._ops

    @property
    def router(self) -> CallbackRouter:
        return self._router

    @property
    def pushed(self) -> int:
        return self._marker.pushed

    def identify(
        self, conn: ConnectionId, identity: ClientIdentity | None = None
    ) -> None:
        """Bind the connection and its declared identity, with no listen leg."""
        self._clients.record(conn, identity)

    def connect(
        self, conn: ConnectionId, identity: ClientIdentity | None = None
    ) -> _Listener:
        """Bring a session up as a live listen leg does: one call, identity and leg."""
        listener = _Listener()
        self._clients.attach_listener(conn, identity or _identity(), listener)
        return listener

    def drop_leg(self, conn: ConnectionId, listener: _Listener) -> None:
        """Tear the session's leg down the way its own teardown does."""
        self._clients.detach_listener(conn, listener)

    def register(self, conn: ConnectionId, callback_id: str = "beads") -> Ok | OpError:
        request = RegisterCallbackRequest.parse(callback_id=callback_id, label="Beads")
        return self._ops.register_callback(request, scope=Scope(conn))

    def click(self, conn: ConnectionId, callback_id: str = "beads") -> Ok | OpError:
        return self._ops.invoke_callback(CallbackInvocation(conn, callback_id).menu_id)

    def held(self, conn: ConnectionId) -> tuple[str, ...]:
        return tuple(inv.callback_id for inv in self._router.pending(conn))


def _identity(name: str = "claude", repo: str = "/w/lux") -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name=name, repo=repo)


def test_registration_requires_a_push_reachable_connection() -> None:
    """The gate that makes the menu contract keepable: no listen leg, no menu item."""
    wired = _Wired()
    conn = ConnectionId("mcp")
    wired.identify(conn, _identity())  # identified, but no listener

    result = wired.register(conn)
    assert isinstance(result, OpError)
    assert result.code == "push_required"
    assert "listen leg" in result.reason
    assert wired.pushed == 0  # nothing registered, nothing pushed


def test_push_reachability_is_answered_before_identity() -> None:
    """A caller that could never be told of a click learns that, not to identify.

    Identifying would not make an MCP or one-shot REST connection deliverable, so
    reporting the identity challenge first would send the caller down a path that
    ends in the same refusal.
    """
    wired = _Wired()
    conn = ConnectionId("bare")  # neither identified nor listening
    result = wired.register(conn)
    assert isinstance(result, OpError)
    assert result.code == "push_required"


def test_a_session_whose_lease_lapsed_is_challenged_rather_than_registered() -> None:
    """Holding a leg is not enough; the session must still be one the Hub knows.

    This is now the only way a session with a leg can be refused on its own
    account. Identity and the leg arrive in one registry write, so a connection
    cannot hold a leg anonymously — the route that serves it refuses an unnamed
    handshake, and attaching records the identity in the same step. What remains
    is a session that stopped renewing, and re-identifying answers that, because
    declaring an identity is itself a renewal.
    """
    clock = _Clock()
    wired = _Wired(clock=clock)
    conn = ConnectionId("mcp")
    wired.connect(conn, _identity())
    clock.advance(1801.0)  # past the 1800s mcp-session lease, no contact since

    result = wired.register(conn)
    assert isinstance(result, OpError)
    assert result.code == "identification_required"
    assert wired.pushed == 0


def test_an_identified_listening_session_registers_and_the_menu_is_pushed() -> None:
    wired = _Wired()
    conn = ConnectionId("mcp")
    wired.connect(conn, _identity())

    assert isinstance(wired.register(conn), Ok)
    assert wired.pushed == 1
    menus = wired.ops.callback_menus()
    assert [menu.label for menu in menus] == ["Clients"]
    # The client is named for the repository it works in, not for its wire name.
    client = menus[0].items[0]
    assert isinstance(client, Menu)
    assert client.label == "lux"


def test_a_malformed_request_passes_through_without_pushing() -> None:
    wired = _Wired()
    conn = ConnectionId("mcp")
    wired.connect(conn, _identity())

    result = wired.register(conn, "")  # empty id
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert wired.pushed == 0


def test_a_click_routes_to_the_owning_session_and_wakes_its_listener() -> None:
    wired = _Wired()
    conn = ConnectionId("mcp")
    listener = wired.connect(conn, _identity())
    wired.register(conn)

    assert isinstance(wired.click(conn), Ok)
    assert listener.woken == 1  # pushed, not left for a poll
    assert wired.held(conn) == ("beads",)  # and buffered until the leg drains it


def test_the_hold_is_bounded() -> None:
    wired = _Wired(capacity=2)
    conn = ConnectionId("mcp")
    wired.connect(conn, _identity())
    wired.register(conn)

    for _ in range(5):
        wired.click(conn)
    assert wired.held(conn) == ("beads", "beads")  # capped at 2


def test_a_click_for_a_departed_session_is_not_found() -> None:
    clock = _Clock()
    wired = _Wired(clock=clock)
    conn = ConnectionId("cli")
    wired.connect(conn, ClientIdentity(kind="cli", name="lux", repo="/w/lux"))
    wired.register(conn)

    clock.advance(91.0)  # past the 90s cli lease — the session leaves the live set
    result = wired.click(conn)
    assert isinstance(result, OpError)
    assert result.code == "not_found"
    assert "gone" in result.reason


def test_a_click_for_an_unregistered_callback_is_not_found() -> None:
    wired = _Wired()
    conn = ConnectionId("mcp")
    wired.connect(conn, _identity())
    wired.register(conn)

    result = wired.click(conn, "other")
    assert isinstance(result, OpError)
    assert result.code == "not_found"


def test_a_malformed_leaf_id_is_invalid_request() -> None:
    result = _Wired().ops.invoke_callback("no-separator")
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"


def test_a_click_is_held_for_only_its_own_session() -> None:
    wired = _Wired()
    vox, lux = ConnectionId("vox"), ConnectionId("lux")
    wired.connect(vox, _identity("vox", "/w/vox"))
    wired.connect(lux, _identity("lux", "/w/lux"))
    wired.register(vox)
    wired.register(lux)

    wired.click(vox)
    assert wired.held(vox) == ("beads",)
    assert wired.held(lux) == ()  # the peer's hold is untouched


def test_a_dropped_listener_closes_the_door_to_new_registrations() -> None:
    """Losing the leg is losing the right to own menu items, not just the pushes.

    A session whose listen leg went away can re-register when it reconnects — the
    reconnect re-adds the listener — but until then it cannot take a new one.
    """
    wired = _Wired()
    conn = ConnectionId("mcp")
    listener = wired.connect(conn, _identity())
    assert isinstance(wired.register(conn), Ok)

    wired.drop_leg(conn, listener)
    result = wired.register(conn, "second")
    assert isinstance(result, OpError)
    assert result.code == "push_required"
