"""Tests for punt_lux.mcp_session -- the streamable-HTTP session lifecycle."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import cast

import anyio
import pytest

from punt_lux.client_host import UNOBSERVED
from punt_lux.hub import disconnect_connection
from punt_lux.hub.hub import Hub
from punt_lux.hub.hub_store_factory import HubStoreFactory
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.mcp_session import SessionRegistry
from punt_lux.mcp_session_manager import LuxSessionManager
from punt_lux.operations.client_listing import ClientListing
from punt_lux.tools.server import bind_session, unbind_session
from punt_lux.wire.model.ids import Topic


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


class TestUncleanDisconnect:
    def test_inner_run_raise_still_runs_full_cleanup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed connection still discards and runs both cleanup legs.

        This is the kill-mid-session path: the SDK session loop dies, but the
        registry entry must drop and the disconnect cascade must run, so a
        crashed session cannot strand its Hub-side state or the live count.
        """
        legs: list[str] = []

        class _Menu:
            def drop_session(self, connection_id: object) -> None:
                legs.append("menu")

        def _record_disconnect(conn: object) -> None:
            legs.append("disconnect")

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", _Menu())
        monkeypatch.setattr(
            "punt_lux.session_cleanup.disconnect_connection", _record_disconnect
        )

        registry = SessionRegistry()

        async def _drive() -> None:
            token = bind_session("unclean", UNOBSERVED)
            try:
                async with AsyncExitStack() as connection:
                    LuxSessionManager._track_connection(registry, connection)
                    raise RuntimeError("connection failed")
            finally:
                unbind_session(token)

        with pytest.raises(RuntimeError, match="connection failed"):
            anyio.run(_drive)

        assert registry.count == 0
        assert legs == ["menu", "disconnect"]


def _open_connection(registry: SessionRegistry, key: str) -> AsyncExitStack:
    connection = AsyncExitStack()
    token = bind_session(key, UNOBSERVED)
    try:
        LuxSessionManager._track_connection(registry, connection)
    finally:
        unbind_session(token)
    return connection


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
            def drop_session(self, connection_id: object) -> None:
                legs.append("menu")

        def _record_disconnect(conn: object) -> None:
            legs.append("disconnect")

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", _Menu())
        monkeypatch.setattr(
            "punt_lux.session_cleanup.disconnect_connection", _record_disconnect
        )

        registry = SessionRegistry()

        async def _drive() -> None:
            async with _open_connection(registry, "sess-a"):
                async with _open_connection(registry, "sess-a"):
                    assert registry.count == 2
                    assert legs == []
                assert registry.count == 1
                assert legs == []

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
        not in which functions got called.
        """
        hub = Hub()
        factory = HubStoreFactory(hub=hub)
        display = factory.display
        lifecycle = factory.lifecycle
        clients = factory.clients
        conn = ConnectionId("sess-shared")

        def _writer(_message: object) -> bool:
            """The shared connection's one Hub-side outbound writer."""
            return True

        lifecycle.arrive(conn, UNOBSERVED)
        hub.register_writer(conn, _writer)
        hub.subscribe(conn, Topic("work.saved"))

        def _disconnect(connection_id: object) -> None:
            disconnect_connection(
                cast("ConnectionId", connection_id), lifecycle=lifecycle
            )

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", _NoopMenu())
        monkeypatch.setattr(
            "punt_lux.session_cleanup.disconnect_connection", _disconnect
        )

        registry = SessionRegistry()

        def _reads() -> tuple[bool, list[str]]:
            client = next(
                c
                for c in ClientListing(display, clients, hub, lambda _c: 0)
                .read()
                .clients
                if c.connection_id == str(conn)
            )
            return client.writer_bound, client.subscribed_topics

        async def _drive() -> None:
            async with _open_connection(registry, "sess-shared"):
                async with _open_connection(registry, "sess-shared"):
                    assert registry.count == 2
                # The survivor's subscription and writer must still be live.
                writer_bound, topics = _reads()
                assert writer_bound is True
                assert topics == ["work.saved"]

        anyio.run(_drive)

        # Now that the last same-key session has left, the shared connection's
        # Hub state is truly gone -- and session_ls no longer lists it at all.
        assert hub.has_writer(conn) is False
        assert hub.topics_for(conn) == frozenset()
        listed = ClientListing(display, clients, hub, lambda _c: 0).read().clients
        assert all(c.connection_id != str(conn) for c in listed)


class _NoopMenu:
    """A menu-leg stub that does nothing; this test only asserts Hub state."""

    def drop_session(self, connection_id: object) -> None:
        """No menu state is exercised here."""
