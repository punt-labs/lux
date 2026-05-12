"""WebSocket session hub for luxd.

Multiplexes MCP sessions onto a single display connection. Each WebSocket
connection is one Claude Code session, identified by ?session_key=<pid>.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from socket import socket
from typing import TYPE_CHECKING

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

DEFAULT_HUB_PORT = 8430

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

_active_sessions: set[str] = set()
_display_connected: bool = False


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def _health_route(request: Request) -> JSONResponse:  # noqa: ARG001
    """Return hub health status."""
    return JSONResponse(
        {
            "status": "ok",
            "sessions": len(_active_sessions),
            "display": _display_connected,
        }
    )


async def _mcp_websocket_route(websocket: WebSocket) -> None:
    """MCP JSON-RPC over WebSocket for mcp-proxy.

    Each connection gets its own MCP session with isolated state.
    Auth is checked before the WebSocket is accepted.
    """
    from mcp.server.websocket import websocket_server

    # Reject cross-site WebSocket hijacking (CSWSH). Browsers always send
    # an Origin header on WebSocket upgrades; non-browser clients (mcp-proxy)
    # do not. If an Origin is present it must match the allowed CORS origins.
    origin = websocket.headers.get("Origin")
    if origin is not None:
        await websocket.close(code=1008)
        return

    # Sanitize user-controlled value before logging (CWE-117).
    raw_key = websocket.query_params.get("session_key", "unknown")
    session_key = _CONTROL_CHAR_RE.sub("", raw_key)[:64]
    logger.info("MCP WebSocket connected: session_key=%s", session_key)

    _active_sessions.add(session_key)
    try:
        async with websocket_server(
            websocket.scope, websocket.receive, websocket.send
        ) as (read_stream, write_stream):
            from punt_lux.tools import run_mcp_session

            await run_mcp_session(read_stream, write_stream, session_key=session_key)
    except Exception:
        logger.exception("MCP WebSocket error: session_key=%s", session_key)
    finally:
        _active_sessions.discard(session_key)
        logger.info("MCP WebSocket disconnected: session_key=%s", session_key)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def build_app(
    *,
    lifespan: Callable[[Starlette], AbstractAsyncContextManager[None]] | None = None,
) -> Starlette:
    """Build the Starlette ASGI application.

    Exposed as a factory so tests can construct the app without starting
    uvicorn -- just wrap with ``starlette.testclient.TestClient``.
    """
    routes = [
        Route("/health", _health_route, methods=["GET"]),
        WebSocketRoute("/mcp", _mcp_websocket_route),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["http://localhost"],
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["Content-Type"],
        ),
    ]

    return Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
    )


# ---------------------------------------------------------------------------
# Port file helpers
# ---------------------------------------------------------------------------


def _write_port_file(port_path: object, port: int) -> None:
    from pathlib import Path

    p = Path(str(port_path))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(port))
    logger.info("Wrote port file: %s (port %d)", p, port)


def _remove_port_file(port_path: object) -> None:
    from pathlib import Path

    p = Path(str(port_path))
    try:
        p.unlink(missing_ok=True)
        logger.info("Removed port file: %s", p)
    except OSError:
        logger.warning("Could not remove port file: %s", p)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def serve(
    host: str = "127.0.0.1",
    port: int = DEFAULT_HUB_PORT,
) -> None:
    """Start the luxd hub. Blocks until shutdown."""
    from punt_lux.paths import hub_port_path

    port_path = hub_port_path()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncGenerator[None]:
        yield
        _remove_port_file(port_path)

    app = build_app(lifespan=lifespan)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_config=None,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # Write the port file after bind so callers always see the actual port
    # (important when port == 0 requests an OS-assigned ephemeral port).
    original_startup = server.startup

    async def _startup_with_port_file(
        sockets: list[socket] | None = None,
    ) -> None:
        await original_startup(sockets=sockets)
        if server.servers and server.servers[0].sockets:
            actual_port = server.servers[0].sockets[0].getsockname()[1]
            _write_port_file(port_path, actual_port)
            logger.info("luxd listening on %s:%d", host, actual_port)
        else:
            logger.error("Server started but no bound sockets; port file not written")

    server.startup = _startup_with_port_file  # type: ignore[method-assign]

    logger.info("Starting luxd on %s:%d", host, port)
    server.run()
    logger.info("luxd stopped")


def main() -> None:
    """Entry point for the luxd binary."""
    import argparse

    parser = argparse.ArgumentParser(description="Lux session hub daemon")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_HUB_PORT, help="Bind port")
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
