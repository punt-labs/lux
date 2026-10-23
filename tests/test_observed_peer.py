"""The Hub observes where a client connected from, at each door, and trusts no claim.

Three doors carry a caller in -- MCP streamable HTTP, REST, and the WebSocket
listen leg -- and each reads the socket peer its framework reports. The host is
recorded on the session in the same write as the identity, kept in first-seen
order per connection (one identity spans several transports), and never read
from a header or a declaration.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Self, final

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.menu_presence import MarkMenusSink
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.mcp_endpoint import McpAsgiApp
from punt_lux.operations.identity import IdentityOperations
from punt_lux.operations.scope import Scope
from punt_lux.peer_host import PeerHost
from punt_lux.protocol.elements.text import TextElement
from punt_lux.tools.server import (
    bind_session,
    current_peer,
    current_session,
    unbind_session,
)
from punt_lux.ws_transport import HubListenTransport

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

_AGENT = ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")
_CONN = ConnectionId("conn")


def _request(
    client: tuple[str, int] | None, headers: dict[str, str] | None = None
) -> Request:
    scope: MutableMapping[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "client": client,
    }
    return Request(scope)


class TestClientSessionPeers:
    def test_a_new_session_has_seen_no_host(self) -> None:
        assert ClientSession(0.0).peers == ()

    def test_a_host_is_recorded(self) -> None:
        assert ClientSession(0.0).observed_from("127.0.0.1").peers == ("127.0.0.1",)

    def test_an_ipv6_loopback_is_recorded_as_reported(self) -> None:
        assert ClientSession(0.0).observed_from("::1").peers == ("::1",)

    def test_no_peer_records_nothing(self) -> None:
        session = ClientSession(0.0)

        assert session.observed_from(None) is session

    def test_a_repeated_host_is_not_duplicated(self) -> None:
        once = ClientSession(0.0).observed_from("127.0.0.1")

        assert once.observed_from("127.0.0.1").peers == ("127.0.0.1",)

    def test_distinct_hosts_keep_first_seen_order(self) -> None:
        session = (
            ClientSession(0.0)
            .observed_from("10.0.0.5")
            .observed_from("127.0.0.1")
            .observed_from("10.0.0.5")
        )

        assert session.peers == ("10.0.0.5", "127.0.0.1")

    def test_every_rebuild_carries_the_hosts_forward(self) -> None:
        seen = ClientSession(0.0).observed_from("127.0.0.1")

        class _Leg:
            def wake(self) -> None:
                """Occupies the slot only."""

        leg = _Leg()
        rebuilt = [
            seen.renewed(1.0),
            seen.with_identity(_AGENT),
            seen.attached(leg),
            seen.attached(leg).detached(leg),
        ]
        callback = (
            seen.with_identity(_AGENT)
            .attached(leg)
            .registering(SessionCallback(id="x", label="X"), 1.0)
        )

        assert all(session is not None for session in rebuilt)
        assert [s.peers for s in rebuilt if s is not None] == [("127.0.0.1",)] * 4
        assert callback is not None
        assert callback.peers == ("127.0.0.1",)


class TestScopePeer:
    def test_defaults_to_no_peer(self) -> None:
        assert Scope(_CONN).peer_host is None

    def test_carries_the_peer_it_is_given(self) -> None:
        assert Scope(_CONN, "127.0.0.1").peer_host == "127.0.0.1"

    def test_two_scopes_for_one_connection_stay_equal_whatever_the_peer(self) -> None:
        assert Scope(_CONN, "127.0.0.1") == Scope(_CONN, "10.0.0.5")
        assert hash(Scope(_CONN, "127.0.0.1")) == hash(Scope(_CONN, None))


class TestPeerHost:
    def test_reads_the_socket_peer(self) -> None:
        assert PeerHost(_request(("127.0.0.1", 5000))).host == "127.0.0.1"

    def test_reads_an_ipv6_peer(self) -> None:
        assert PeerHost(_request(("::1", 5000))).host == "::1"

    def test_a_server_that_reports_no_peer_gives_none(self) -> None:
        assert PeerHost(_request(None)).host is None

    def test_never_reads_a_forwarding_header(self) -> None:
        request = _request(("127.0.0.1", 5000), {"X-Forwarded-For": "10.9.9.9"})

        assert PeerHost(request).host == "127.0.0.1"


class TestRegistryRecordsThePeer:
    def test_identifying_records_the_peer_in_the_same_write(self) -> None:
        factory = HubStoreFactory(hub=Hub())

        factory.lifecycle.identify(_CONN, _AGENT, "127.0.0.1")

        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert session.peers == ("127.0.0.1",)

    def test_a_contact_that_reports_no_peer_records_none(self) -> None:
        factory = HubStoreFactory(hub=Hub())

        factory.lifecycle.identify(_CONN, _AGENT)

        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert session.peers == ()

    def test_rest_then_websocket_from_one_host_reports_one_host(self) -> None:
        factory = HubStoreFactory(hub=Hub())
        factory.lifecycle.identify(_CONN, _AGENT, "127.0.0.1")

        class _Leg:
            def wake(self) -> None:
                """Occupies the slot only."""

        factory.lifecycle.attach(_CONN, _AGENT, _Leg(), "127.0.0.1")

        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert session.peers == ("127.0.0.1",)

    def test_a_second_distinct_host_appends_in_first_seen_order(self) -> None:
        factory = HubStoreFactory(hub=Hub())
        factory.lifecycle.identify(_CONN, _AGENT, "10.0.0.5")
        factory.lifecycle.identify(_CONN, _AGENT, "127.0.0.1")
        factory.lifecycle.identify(_CONN, _AGENT, "10.0.0.5")

        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert session.peers == ("10.0.0.5", "127.0.0.1")

    def test_a_declared_host_is_not_a_field_of_an_identity(self) -> None:
        with pytest.raises(ValidationError):
            ClientIdentity.model_validate(
                {"kind": "cli", "name": "x", "host": "10.1.1.1"}
            )


@final
class _Marker:
    scenes: list[SceneId]
    __slots__ = ("scenes",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.scenes = []
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.scenes.append(scene_id)

    def mark_menus(self) -> None:
        """Menus are not what this test observes."""


class TestAHostFlowsToTheFacts:
    """A new distinct host resends the owner's scenes, so the popup row is fresh."""

    def test_a_new_peer_with_the_same_identity_marks_the_scenes_dirty(self) -> None:
        factory = HubStoreFactory(hub=Hub())
        marker = _Marker()
        factory.lifecycle.present_as(marker, MarkMenusSink(marker))
        factory.lifecycle.identify(_CONN, _AGENT, "127.0.0.1")
        scene = SceneId("s1")
        factory.display.replace_scene(_CONN, scene, [TextElement(id="t", content="x")])
        marker.scenes.clear()

        factory.lifecycle.identify(_CONN, _AGENT, "10.0.0.5")

        assert marker.scenes == [scene]

    def test_the_same_peer_again_marks_nothing(self) -> None:
        factory = HubStoreFactory(hub=Hub())
        marker = _Marker()
        factory.lifecycle.present_as(marker, MarkMenusSink(marker))
        factory.lifecycle.identify(_CONN, _AGENT, "127.0.0.1")
        factory.display.replace_scene(
            _CONN, SceneId("s1"), [TextElement(id="t", content="x")]
        )
        marker.scenes.clear()

        factory.lifecycle.identify(_CONN, _AGENT, "127.0.0.1")

        assert marker.scenes == []


class TestIdentityOperationsPassesThePeer:
    def test_identify_records_the_scopes_peer(self) -> None:
        factory = HubStoreFactory(hub=Hub())
        ops = IdentityOperations(factory.lifecycle, factory.clients)

        ops.identify(
            {"kind": "mcp-session", "name": "claude", "repo": "/w/lux"},
            scope=Scope(_CONN, "10.0.0.5"),
        )

        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert session.peers == ("10.0.0.5",)

    def test_a_scope_without_a_peer_records_none(self) -> None:
        factory = HubStoreFactory(hub=Hub())
        ops = IdentityOperations(factory.lifecycle, factory.clients)

        ops.identify({"kind": "cli", "name": "x"}, scope=Scope(_CONN))

        session = factory.clients.session_of(_CONN)
        assert session is not None
        assert session.peers == ()


class TestMcpBinding:
    def test_the_default_peer_is_none(self) -> None:
        assert current_peer() is None

    def test_a_binding_carries_key_and_peer_and_releases_both(self) -> None:
        binding = bind_session("sess", "127.0.0.1")
        try:
            assert (current_session(), current_peer()) == ("sess", "127.0.0.1")
        finally:
            unbind_session(binding)

        assert (current_session(), current_peer()) == ("local", None)

    def test_a_binding_without_a_peer_leaves_it_unknown(self) -> None:
        binding = bind_session("sess")
        try:
            assert current_peer() is None
        finally:
            unbind_session(binding)

    def test_bindings_nest_and_unwind(self) -> None:
        outer = bind_session("outer", "10.0.0.5")
        inner = bind_session("inner", "::1")
        assert current_peer() == "::1"
        unbind_session(inner)
        assert (current_session(), current_peer()) == ("outer", "10.0.0.5")
        unbind_session(outer)

    def test_the_tool_scope_carries_the_bound_peer(self) -> None:
        from punt_lux.tools import tools as core_tools

        binding = bind_session("sess", "127.0.0.1")
        try:
            assert core_tools.scope().peer_host == "127.0.0.1"
            assert core_tools.scope().connection_id == ConnectionId("sess")
        finally:
            unbind_session(binding)

    def test_a_tool_scope_with_no_binding_has_no_peer(self) -> None:
        from punt_lux.tools import tools as core_tools

        assert core_tools.scope().peer_host is None


@final
class _CapturingManager:
    """Stands in for the SDK's session manager: records what the context holds."""

    seen: list[tuple[str, str | None]]
    # None = the request is served; an exception = the SDK raises after the
    # context was read, as a failing session would.
    _failure: Exception | None
    __slots__ = ("_failure", "seen")

    def __new__(cls, failure: Exception | None = None) -> Self:
        self = super().__new__(cls)
        self.seen = []
        self._failure = failure
        return self

    async def handle_request(self, scope: Any, receive: Any, send: Any) -> None:
        self.seen.append((current_session(), current_peer()))
        if self._failure is not None:
            raise self._failure


async def _drive(
    client: tuple[str, int] | None,
    query: bytes = b"session_key=abc",
    manager: _CapturingManager | None = None,
) -> _CapturingManager:
    manager = manager if manager is not None else _CapturingManager()
    app = McpAsgiApp(manager)  # type: ignore[arg-type]  # a capturing double
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "query_string": query,
        "headers": [],
        "client": client,
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request"}

    async def send(_message: dict[str, object]) -> None:
        return None

    await app(scope, receive, send)  # type: ignore[arg-type]
    return manager


class TestMcpDoor:
    @pytest.mark.anyio
    async def test_binds_the_socket_peer_beside_the_session_key(self) -> None:
        manager = await _drive(("127.0.0.1", 5000))

        assert manager.seen == [("abc", "127.0.0.1")]
        assert (current_session(), current_peer()) == ("local", None)

    @pytest.mark.anyio
    async def test_a_raising_manager_still_releases_both_bindings(self) -> None:
        manager = _CapturingManager(RuntimeError("the session failed"))

        with pytest.raises(RuntimeError, match="the session failed"):
            await _drive(("127.0.0.1", 5000), manager=manager)

        # The body saw both bindings, and neither outlives it.
        assert manager.seen == [("abc", "127.0.0.1")]
        assert (current_session(), current_peer()) == ("local", None)

    @pytest.mark.anyio
    async def test_a_raising_manager_releases_a_peerless_binding_too(self) -> None:
        manager = _CapturingManager(RuntimeError("the session failed"))

        with pytest.raises(RuntimeError, match="the session failed"):
            await _drive(None, manager=manager)

        assert manager.seen == [("abc", None)]
        assert (current_session(), current_peer()) == ("local", None)

    @pytest.mark.anyio
    async def test_an_ipv6_peer_is_bound_as_reported(self) -> None:
        manager = await _drive(("::1", 5000))

        assert manager.seen == [("abc", "::1")]

    @pytest.mark.anyio
    async def test_a_request_with_no_peer_binds_none(self) -> None:
        manager = await _drive(None)

        assert manager.seen == [("abc", None)]


class TestRestDoor:
    def _caller(self) -> Any:
        from punt_lux.rest.identity import RestCaller
        from punt_lux.rest.status import HttpErrorMap

        factory = HubStoreFactory(hub=Hub())
        ops = _Ops(IdentityOperations(factory.lifecycle, factory.clients))
        return RestCaller(ops, HttpErrorMap()), factory  # type: ignore[arg-type]

    def test_the_resolved_scope_carries_the_socket_peer(self) -> None:
        caller, factory = self._caller()
        request = _request(("127.0.0.1", 5000), _headers())

        scope = caller.resolve(request)

        assert scope.peer_host == "127.0.0.1"
        session = factory.clients.session_of(scope.connection_id)
        assert session is not None
        assert session.peers == ("127.0.0.1",)

    def test_an_ipv6_peer_is_recorded(self) -> None:
        caller, factory = self._caller()

        scope = caller.resolve(_request(("::1", 5000), _headers()))

        session = factory.clients.session_of(scope.connection_id)
        assert session is not None
        assert session.peers == ("::1",)

    def test_a_forwarding_header_is_not_the_recorded_host(self) -> None:
        caller, factory = self._caller()
        headers = {**_headers(), "X-Forwarded-For": "10.9.9.9"}

        scope = caller.resolve(_request(("127.0.0.1", 5000), headers))

        session = factory.clients.session_of(scope.connection_id)
        assert session is not None
        assert session.peers == ("127.0.0.1",)

    def test_a_request_with_no_peer_records_none(self) -> None:
        caller, factory = self._caller()

        scope = caller.resolve(_request(None, _headers()))

        session = factory.clients.session_of(scope.connection_id)
        assert session is not None
        assert session.peers == ()

    def test_an_unidentified_request_is_still_refused(self) -> None:
        caller, _ = self._caller()

        with pytest.raises(HTTPException):
            caller.resolve(_request(("127.0.0.1", 5000)))


def _headers() -> dict[str, str]:
    return {
        "X-Lux-Client-Kind": "app",
        "X-Lux-Client-Name": "voxd",
        "X-Lux-Client-Repo": "/w/vox",
    }


@final
class _Ops:
    """The slice of the operations facade a session identify reaches."""

    _identity: IdentityOperations
    __slots__ = ("_identity",)

    def __new__(cls, identity: IdentityOperations) -> Self:
        self = super().__new__(cls)
        self._identity = identity
        return self

    def identify(self, declaration: dict[str, object], *, scope: Scope) -> Any:
        return self._identity.identify(declaration, scope=scope)


class TestWebSocketDoor:
    def _wired(self) -> tuple[TestClient, HubStoreFactory]:
        hub = Hub()
        factory = HubStoreFactory(hub=hub)
        marker = _Marker()
        factory.lifecycle.present_as(marker, MarkMenusSink(marker))
        app = FastAPI()
        HubListenTransport(
            hub,
            factory.lifecycle,
            factory.clients.legs,
            CallbackRouter(factory.clients),
            marker,
        ).mount(app)
        return TestClient(app), factory

    def test_the_listen_leg_records_the_socket_peer(self) -> None:
        client, factory = self._wired()
        conn = connection_for({"kind": "app", "name": "voxd", "repo": "/w/vox"})

        with client.websocket_connect("/ws", headers=_headers()) as ws:
            ws.receive_json()  # ready: the leg holds the slot, the peer is recorded
            _eventually(lambda: factory.clients.session_of(conn) is not None)
            session = factory.clients.session_of(conn)
            assert session is not None
            # Starlette's TestClient reports the peer host it simulates.
            assert session.peers == ("testclient",)


def _eventually(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached within timeout")
