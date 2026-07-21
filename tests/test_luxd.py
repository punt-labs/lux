"""Tests for punt_lux.luxd -- WebSocket session hub process entry point."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from punt_lux.luxd import (
    DEFAULT_HUB_PORT,
    _active_sessions,
    _sanitize_for_log,
    build_app,
)


class TestSanitizeForLog:
    def test_strips_control_characters(self):
        """Control characters (log-injection vectors) are removed before logging."""
        assert _sanitize_for_log("evil\r\nINJECTED\x00tail") == "evilINJECTEDtail"

    def test_none_logs_as_empty_string(self):
        assert _sanitize_for_log(None) == ""

    def test_caps_length(self):
        assert len(_sanitize_for_log("x" * 200)) == 64


class TestHealthRoute:
    def test_returns_ok(self):
        app = build_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["sessions"] == 0
        assert "display" not in data

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

    def test_accepts_loopback_host(self):
        """A loopback Host passes the SDK guard -- this is how mcp-proxy dials in."""
        app = build_app()
        client = TestClient(app)
        _active_sessions.discard("loopback")
        with client.websocket_connect(
            "/mcp?session_key=loopback",
            headers={"Host": f"127.0.0.1:{DEFAULT_HUB_PORT}"},
        ):
            assert "loopback" in _active_sessions
        assert "loopback" not in _active_sessions

    def test_rejects_foreign_host(self):
        """A non-loopback Host is rejected by the SDK DNS-rebinding guard."""
        app = build_app()
        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/mcp?session_key=foreign", headers={"Host": "evil.example:9"}
            ),
        ):
            pass

    def test_session_cleanup_after_disconnect(self):
        """The session is counted while open, then removed after disconnect."""
        app = build_app()
        client = TestClient(app)
        _active_sessions.discard("test-pid")
        with client.websocket_connect(
            "/mcp?session_key=test-pid",
            headers={"Host": f"127.0.0.1:{DEFAULT_HUB_PORT}"},
        ):
            # The handshake opened, so the session must be registered and counted;
            # a failed handshake would raise here instead of reporting a session.
            assert client.get("/health").json()["sessions"] >= 1
        assert "test-pid" not in _active_sessions


class TestBuildApp:
    def test_returns_starlette_app(self):
        app = build_app()
        # FastAPI is a Starlette subclass, so the same attributes hold.
        assert hasattr(app, "router")
        assert hasattr(app, "routes")

    def test_has_health_and_mcp_routes(self):
        app = build_app()
        paths = [getattr(r, "path", None) for r in app.routes]
        assert "/health" in paths
        assert "/mcp" in paths


class TestRestSurfaceMounted:
    """The typed REST surface is live on the same app luxd serves.

    These tests use ``build_app()``, which wires the surface over the process-wide
    Hub singletons via ``RestSurface.for_hub()``. That is deliberate but only safe
    for read-only routes like these — they observe shared state, they never mutate
    it. A test that renders, clears, writes display mode, or otherwise mutates Hub
    state must use the fake-backed ``tests/rest`` ``make_client`` path instead, so
    it runs against a fresh HubDisplay and cannot bleed state across tests.
    """

    def test_health_returns_the_typed_body(self):
        client = TestClient(build_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert isinstance(resp.json()["sessions"], int)

    def test_a_rest_route_is_reachable(self):
        # A real HTTP request against the assembled app reaches a REST route and
        # gets a typed result — the surface is mounted, not merely importable.
        client = TestClient(build_app())
        resp = client.get("/scenes")
        assert resp.status_code == 200
        body = resp.json()
        assert "scenes" in body
        assert "frames" in body
