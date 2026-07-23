"""Tests for punt_lux.mcp_session -- the streamable-HTTP session lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import anyio
import pytest
from mcp.shared.message import SessionMessage

from punt_lux.mcp_session import SessionRegistry, SessionScopedServer
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

    def test_distinct_keys_each_count(self) -> None:
        registry = SessionRegistry()
        registry.add("sess-a")
        registry.add("sess-b")
        assert registry.count == 2

    def test_discard_removes_a_session(self) -> None:
        registry = SessionRegistry()
        registry.add("sess-a")
        registry.discard("sess-a")
        assert registry.count == 0

    def test_discard_absent_is_a_noop(self) -> None:
        registry = SessionRegistry()
        registry.discard("never-added")  # must not raise or go negative
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
            def drop_session(self, scope: object) -> None:
                legs.append("menu")

        def _record_disconnect(conn: object, drop: object) -> None:
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
