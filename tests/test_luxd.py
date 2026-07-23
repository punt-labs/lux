"""Tests for punt_lux.luxd -- the streamable-HTTP session hub entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from punt_lux.luxd import build_app, serve
from punt_lux.mcp_transport import McpHttpTransport
from punt_lux.rest.app import DEFAULT_SCOPE
from punt_lux.session_key import RESERVED_REST_CONNECTION

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class TestHealthRoute:
    def test_returns_ok_with_zero_sessions(self):
        client = TestClient(build_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["sessions"] == 0
        assert "display" not in data


class TestMcpRoute:
    def test_rejects_reserved_rest_session_key(self):
        """A session_key colliding with the REST scope id is refused (403).

        Otherwise the session would share REST-owned scene/menu state and its
        disconnect cascade would destroy REST-created state. The refusal precedes
        the transport's own Host/Origin guard, so it holds for any Host.
        """
        with TestClient(build_app()) as client:
            resp = client.post(
                f"/mcp?session_key={RESERVED_REST_CONNECTION}",
                headers={"content-type": "application/json"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            )
        assert resp.status_code == 403

    def test_rejects_foreign_host(self):
        """A non-loopback Host is rejected by the SDK DNS-rebinding guard (421)."""
        with TestClient(build_app()) as client:
            resp = client.post(
                "/mcp?session_key=foreign",
                headers={
                    "content-type": "application/json",
                    "host": "evil.example:9",
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            )
        assert resp.status_code == 421

    def test_accepts_loopback_host(self):
        """A loopback Host passes the DNS-rebinding guard — the positive case.

        The negative (foreign Host -> 421) is meaningless without proving the
        guard admits the host luxd actually binds. A loopback Host is not
        rejected as a rebinding attempt; the request reaches the MCP layer.
        """
        with TestClient(build_app()) as client:
            resp = client.post(
                "/mcp?session_key=loopback",
                headers={
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                    "host": "127.0.0.1:8430",
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            )
        assert resp.status_code != 421
        assert resp.status_code != 403

    def test_rejects_cross_site_origin(self):
        """A loopback Host with a foreign Origin is refused (CSWSH guard, 403).

        The Host guard passing is not enough: a browser page on another origin
        can send a loopback Host, so the SDK also validates Origin against the
        loopback allowlist and refuses a cross-site Origin.
        """
        with TestClient(build_app()) as client:
            resp = client.post(
                "/mcp?session_key=xsite",
                headers={
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                    "host": "127.0.0.1:8430",
                    "origin": "http://evil.com",
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            )
        assert resp.status_code == 403


class TestReservedRestIdentity:
    def test_rest_scope_is_the_reserved_connection(self):
        """The REST scope and luxd's refusal read one constant, not two strings.

        The reserved identity lives in one place; the REST surface scopes to it
        and luxd refuses a session that would collide with it, so the two sides
        can never drift apart.
        """
        assert DEFAULT_SCOPE.connection_id == RESERVED_REST_CONNECTION


class TestBuildApp:
    def test_returns_fastapi_app(self):
        assert isinstance(build_app(), FastAPI)

    def test_has_health_and_mcp_routes(self):
        app = build_app()
        paths = [getattr(r, "path", None) for r in app.routes]
        assert "/health" in paths
        assert "/mcp" in paths


class TestLifespanOrdering:
    def test_caller_lifespan_wraps_transport_lifespan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The caller lifespan is outermost, so on shutdown the transport
        (session drain + cleanup) unwinds before the caller's writer stops —
        otherwise cleanup's display effects would land on a dead replicator."""
        order: list[str] = []

        @asynccontextmanager
        async def _transport_lifespan(self: McpHttpTransport) -> AsyncGenerator[None]:
            order.append("transport-enter")
            try:
                yield
            finally:
                order.append("transport-exit")

        monkeypatch.setattr(McpHttpTransport, "lifespan", _transport_lifespan)

        @asynccontextmanager
        async def _caller(app: FastAPI) -> AsyncGenerator[None]:
            order.append("caller-enter")
            try:
                yield
            finally:
                order.append("caller-exit")

        app = build_app(lifespan=_caller)

        async def _cycle() -> None:
            async with app.router.lifespan_context(app):
                pass

        anyio.run(_cycle)

        assert order == [
            "caller-enter",
            "transport-enter",
            "transport-exit",
            "caller-exit",
        ]


class TestStartupBindGuard:
    def test_refuses_non_loopback_host_at_startup(self):
        """serve() refuses an off-loopback bind before it ever binds a socket."""
        with pytest.raises(SystemExit) as exc:
            serve(host="192.0.2.1")
        assert exc.value.code == 2


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
