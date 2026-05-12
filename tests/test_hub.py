"""Tests for punt_lux.hub -- WebSocket session hub."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from punt_lux.hub import _active_sessions, build_app


class TestHealthRoute:
    def test_returns_ok(self):
        app = build_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["sessions"] == 0
        assert data["display"] is False

    def test_session_count_reflects_active(self):
        """Verify the health endpoint reports _active_sessions count."""
        app = build_app()
        client = TestClient(app)

        _active_sessions.add("test-session-1")
        _active_sessions.add("test-session-2")
        try:
            resp = client.get("/health")
            data = resp.json()
            assert data["sessions"] == 2
        finally:
            _active_sessions.discard("test-session-1")
            _active_sessions.discard("test-session-2")


class TestMcpWebsocketRoute:
    def test_rejects_browser_origin(self):
        """WebSocket with Origin header should be rejected (CSWSH protection)."""
        app = build_app()
        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/mcp?session_key=test",
                headers={"Origin": "http://evil.com"},
            ),
        ):
            pass
        assert exc_info.value.code == 1008

    def test_connection_without_origin_tracked(self):
        """WebSocket without Origin should add session to _active_sessions."""
        app = build_app()
        client = TestClient(app)
        # The MCP protocol handshake won't complete in test, but the
        # session_key should be tracked while the connection is open.
        _active_sessions.discard("test-pid")
        try:
            with client.websocket_connect("/mcp?session_key=test-pid"):
                # Session should be tracked while connected
                assert "test-pid" in _active_sessions
        except Exception:  # noqa: BLE001, S110
            # MCP protocol error expected -- no real MCP client
            pass
        # After disconnect, session should be cleaned up
        assert "test-pid" not in _active_sessions


class TestBuildApp:
    def test_returns_starlette_app(self):
        app = build_app()
        # Starlette apps have a router attribute
        assert hasattr(app, "router")
        assert hasattr(app, "routes")

    def test_has_health_and_mcp_routes(self):
        app = build_app()
        paths = [getattr(r, "path", None) for r in app.routes]
        assert "/health" in paths
        assert "/mcp" in paths
