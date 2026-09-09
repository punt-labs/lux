"""Tests for punt_lux.mcp_session -- the streamable-HTTP session lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

import anyio
import pytest
from mcp.shared.message import SessionMessage

from punt_lux.domain.hub import disconnect_connection
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.mcp_session import SessionRegistry, SessionScopedServer
from punt_lux.operations.client_listing import ClientListing
from punt_lux.tools.server import bind_session, unbind_session

if TYPE_CHECKING:
    from mcp.server.lowlevel import Server as MCPServer


class TestSessionRegistry:
    def test_starts_empty(self) -> None:
        assert SessionRegistry().count == 0

    def test_add_counts_a_session(self) -> None:
        registry = SessionRegistry()
        registry.add("sess-a")
        assert registry.count == 1

    def test_duplicate_key_counts_per_instance(self) -> None:
        """Two sessions under one key count as two, not one (they are distinct)."""
        registry = SessionRegistry()
        registry.add("sess-a")
        registry.add("sess-a")
        assert registry.count == 2

    def test_first_disconnect_leaves_the_same_key_peer_live(self) -> None:
        """Discarding one of two same-key sessions leaves the peer counted."""
        registry = SessionRegistry()
        registry.add("sess-a")
        registry.add("sess-a")
        registry.discard("sess-a")
        assert registry.count == 1
        registry.discard("sess-a")
        assert registry.count == 0

    def test_discard_reports_last_out(self) -> None:
        """discard is False while a same-key peer remains, True on the last exit."""
        registry = SessionRegistry()
        registry.add("sess-a")
        registry.add("sess-a")
        assert registry.discard("sess-a") is False  # peer still live
        assert registry.discard("sess-a") is True  # last one out

    def test_distinct_keys_each_count(self) -> None:
        registry = SessionRegistry()
        registry.add("sess-a")
        registry.add("sess-b")
        assert registry.count == 2

    def test_discard_removes_a_session(self) -> None:
        registry = SessionRegistry()
        registry.add("sess-a")
        assert registry.discard("sess-a") is True
        assert registry.count == 0

    def test_discard_absent_is_a_noop(self) -> None:
        registry = SessionRegistry()
        assert registry.discard("never-added") is True  # drained, no raise/negative
        assert registry.count == 0


class _RaisingInner:
    """A wrapped MCP server whose session loop dies mid-session."""

    async def run(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("inner run exploded")

    def create_initialization_options(self) -> object:
        return object()


class TestUncleanDisconnect:
    def test_inner_run_raise_still_runs_full_cleanup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An inner run() that raises still discards and runs both cleanup legs.

        This is the kill-mid-session path: the SDK session loop dies, but the
        registry entry must drop and the disconnect cascade must run, so a
        crashed session cannot strand its Hub-side state or the live count.
        """
        legs: list[str] = []

        class _Menu:
            def drop_session(self) -> None:
                legs.append("menu")

        def _record_disconnect(conn: object) -> None:
            legs.append("disconnect")

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", _Menu())
        monkeypatch.setattr(
            "punt_lux.session_cleanup.disconnect_connection", _record_disconnect
        )

        registry = SessionRegistry()
        scoped = SessionScopedServer(
            cast("MCPServer[object, object]", _RaisingInner()), registry
        )

        async def _drive() -> None:
            _send_read, recv_read = anyio.create_memory_object_stream[
                SessionMessage | Exception
            ](0)
            send_write, _recv_write = anyio.create_memory_object_stream[SessionMessage](
                0
            )
            token = bind_session("unclean")
            try:
                await scoped.run(
                    recv_read, send_write, scoped.create_initialization_options()
                )
            finally:
                unbind_session(token)

        with pytest.raises(RuntimeError, match="inner run exploded"):
            anyio.run(_drive)

        assert registry.count == 0
        assert legs == ["menu", "disconnect"]


class _GatedInner:
    """A wrapped MCP server whose session loop blocks until its gate is set."""

    _gate: anyio.Event
    __slots__ = ("_gate",)

    def __new__(cls, gate: anyio.Event) -> Self:
        self = super().__new__(cls)
        self._gate = gate
        return self

    async def run(self, *args: object, **kwargs: object) -> None:
        await self._gate.wait()

    def create_initialization_options(self) -> object:
        return object()


class TestSharedKeyCleanup:
    def test_first_same_key_disconnect_spares_the_peers_hub_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two sessions share a key; the first out runs no cleanup, the last one does.

        Cleanup keys on the shared ``ConnectionId``, so running it when the first
        of two same-key sessions leaves would wipe the still-live peer's menus,
        scenes, subscriptions, and inbox. The teardown must wait for the last
        same-key session to leave — proven here by recording the cleanup legs and
        asserting none fire until both sessions have exited.
        """
        legs: list[str] = []

        class _Menu:
            def drop_session(self) -> None:
                legs.append("menu")

        def _record_disconnect(conn: object) -> None:
            legs.append("disconnect")

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", _Menu())
        monkeypatch.setattr(
            "punt_lux.session_cleanup.disconnect_connection", _record_disconnect
        )

        registry = SessionRegistry()

        async def _session(server: SessionScopedServer) -> None:
            _send_read, recv_read = anyio.create_memory_object_stream[
                SessionMessage | Exception
            ](0)
            send_write, _recv_write = anyio.create_memory_object_stream[SessionMessage](
                0
            )
            token = bind_session("sess-a")
            try:
                await server.run(
                    recv_read, send_write, server.create_initialization_options()
                )
            finally:
                unbind_session(token)

        async def _drive() -> None:
            gate_first = anyio.Event()
            gate_last = anyio.Event()
            first = SessionScopedServer(
                cast("MCPServer[object, object]", _GatedInner(gate_first)), registry
            )
            last = SessionScopedServer(
                cast("MCPServer[object, object]", _GatedInner(gate_last)), registry
            )
            async with anyio.create_task_group() as tg:
                tg.start_soon(_session, first)
                tg.start_soon(_session, last)
                while registry.count < 2:  # both sessions registered and blocked
                    await anyio.sleep(0)
                assert legs == []
                gate_first.set()  # first same-key session leaves
                while registry.count > 1:
                    await anyio.sleep(0)
                assert registry.count == 1  # peer still counted
                assert legs == []  # peer's Hub state untouched
                gate_last.set()  # last same-key session leaves

        anyio.run(_drive)

        assert registry.count == 0
        assert legs == ["menu", "disconnect"]  # cleanup ran once, on the last exit


class TestSharedKeyDisconnectPreservesSubscriptions:
    def test_first_disconnect_leaves_the_survivors_subscription_and_writer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two same-key sessions share one connection's Hub subscription state.

        This drives the real ``disconnect_connection`` (not a recording stub)
        against an isolated ``Hub``/``HubDisplay`` pair, then reads the outcome
        back through :class:`ClientListing` -- the same read ``session_ls``
        serves -- so the proof is in ``subscribed_topics``/``writer_bound``,
        not in which functions got called (lux-95zt).
        """
        hub = Hub()
        display = HubDisplay(hub=hub)
        conn = ConnectionId("sess-shared")

        def _writer(_message: object) -> None:
            """The shared connection's one Hub-side outbound writer."""

        display.register_client(conn)
        hub.register_writer(conn, _writer)
        hub.subscribe(conn, Topic("work.saved"))

        def _disconnect(connection_id: object) -> None:
            disconnect_connection(
                cast("ConnectionId", connection_id), hub_display=display
            )

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", _NoopMenu())
        monkeypatch.setattr(
            "punt_lux.session_cleanup.disconnect_connection", _disconnect
        )

        registry = SessionRegistry()

        def _reads() -> tuple[bool, list[str]]:
            client = next(
                c
                for c in ClientListing(display, hub, lambda _c: 0).read().clients
                if c.connection_id == str(conn)
            )
            return client.writer_bound, client.subscribed_topics

        async def _session(server: SessionScopedServer) -> None:
            _send_read, recv_read = anyio.create_memory_object_stream[
                SessionMessage | Exception
            ](0)
            send_write, _recv_write = anyio.create_memory_object_stream[SessionMessage](
                0
            )
            token = bind_session("sess-shared")
            try:
                await server.run(
                    recv_read, send_write, server.create_initialization_options()
                )
            finally:
                unbind_session(token)

        async def _drive() -> None:
            gate_first = anyio.Event()
            gate_last = anyio.Event()
            first = SessionScopedServer(
                cast("MCPServer[object, object]", _GatedInner(gate_first)), registry
            )
            last = SessionScopedServer(
                cast("MCPServer[object, object]", _GatedInner(gate_last)), registry
            )
            async with anyio.create_task_group() as tg:
                tg.start_soon(_session, first)
                tg.start_soon(_session, last)
                while registry.count < 2:
                    await anyio.sleep(0)
                gate_first.set()  # first same-key session leaves
                while registry.count > 1:
                    await anyio.sleep(0)
                # The survivor's subscription and writer must still be live.
                writer_bound, topics = _reads()
                assert writer_bound is True
                assert topics == ["work.saved"]
                gate_last.set()  # last same-key session leaves

        anyio.run(_drive)

        # Now that the last same-key session has left, the shared connection's
        # Hub state is truly gone -- and session_ls no longer lists it at all.
        assert hub.has_writer(conn) is False
        assert hub.topics_for(conn) == frozenset()
        clients = ClientListing(display, hub, lambda _c: 0).read().clients
        assert all(c.connection_id != str(conn) for c in clients)


class _NoopMenu:
    """A menu-leg stub that does nothing; this test only asserts Hub state."""

    def drop_session(self) -> None:
        """No menu state is exercised here."""
