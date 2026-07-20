"""luxd — the Lux daemon process entry point.

Boots the WebSocket session hub: it multiplexes MCP sessions (one per Claude
Code session, keyed by ``?session_key=<pid>``) onto a single display connection.
Domain state lives in ``punt_lux.domain.hub``; this module bootstraps transport.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from socket import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse

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

_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1"})

_active_sessions: set[str] = set()


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def _health_route(request: Request) -> JSONResponse:  # noqa: ARG001
    """Return hub health status."""
    return JSONResponse({"status": "ok", "sessions": len(_active_sessions)})


async def _mcp_websocket_route(websocket: WebSocket) -> None:
    """MCP JSON-RPC over WebSocket for mcp-proxy.

    Each connection gets its own isolated MCP session; auth is checked first.
    """
    # WebSocket is the deliberate luxd<->mcp-proxy transport leg, supported
    # through mcp 1.x; a streamable-HTTP migration is tracked as future work.
    from mcp.server.websocket import (
        websocket_server,  # pyright: ignore[reportDeprecated]
    )

    # Sanitize user-controlled value before logging (CWE-117).
    raw_key = websocket.query_params.get("session_key", "")
    if not raw_key:
        import uuid

        raw_key = str(uuid.uuid4())[:8]
    session_key = _CONTROL_CHAR_RE.sub("", raw_key)[:64]

    # Reject cross-site WebSocket hijacking (CSWSH): browsers always send an
    # Origin on WebSocket upgrades, non-browser clients (mcp-proxy) do not.
    # Allowlist localhost origins for Electron-based editors.
    origin = websocket.headers.get("Origin")
    if origin is not None and urlparse(origin).hostname not in _ALLOWED_HOSTS:
        logger.warning("Rejected CSWSH: Origin=%s, session_key=%s", origin, session_key)
        await websocket.close(code=1008)
        return

    logger.info("MCP WebSocket connected: session_key=%s", session_key)

    _active_sessions.add(session_key)
    try:
        async with websocket_server(  # pyright: ignore[reportDeprecated]
            websocket.scope, websocket.receive, websocket.send
        ) as (read_stream, write_stream):
            from punt_lux.tools import run_mcp_session

            await run_mcp_session(read_stream, write_stream, session_key=session_key)
    except Exception:
        logger.exception("MCP WebSocket error: session_key=%s", session_key)
    finally:
        _active_sessions.discard(session_key)
        # On close, cascade cleanup drops the HubDisplay registration, marks
        # every owned root removed (the Observer cascade prunes the rest), purges
        # the connection's topic scope, and unbinds its outbound writer.
        from punt_lux.domain.hub import disconnect_connection
        from punt_lux.domain.ids import ConnectionId
        from punt_lux.tools.inbox import drop_session

        disconnect_connection(ConnectionId(session_key), drop_session)
        logger.info("MCP WebSocket disconnected: session_key=%s", session_key)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def build_app(
    *,
    lifespan: Callable[[Starlette], AbstractAsyncContextManager[None]] | None = None,
) -> Starlette:
    """Build the Starlette ASGI application.

    A factory so tests can construct the app without uvicorn, via ``TestClient``.
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
    p = Path(str(port_path))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(port))
    logger.info("Wrote port file: %s (port %d)", p, port)


def _remove_port_file(port_path: object) -> None:
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
    from punt_lux.hub_paths import HubPaths

    hub_paths = HubPaths()
    pid_path = hub_paths.pid_path
    port_path = hub_paths.port_path

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncGenerator[None]:
        # The one background writer to the display starts and stops with luxd.
        from punt_lux.domain.hub.replicator_instance import hub_replicator

        hub_replicator.start()
        try:
            yield
        finally:
            hub_replicator.stop()
            _remove_port_file(port_path)
            pid_path.unlink(missing_ok=True)

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

    # Write the port file after bind so callers see the real (maybe ephemeral) port.
    original_startup = server.startup

    async def _startup_with_port_file(
        sockets: list[socket] | None = None,
    ) -> None:
        await original_startup(sockets=sockets)
        if server.servers and server.servers[0].sockets:
            actual_port = server.servers[0].sockets[0].getsockname()[1]
            _write_port_file(port_path, actual_port)
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(os.getpid()))
            logger.info(
                "luxd listening on %s:%d (pid %d)", host, actual_port, os.getpid()
            )
        else:
            logger.error("Server started but no bound sockets; port file not written")

    server.startup = _startup_with_port_file  # type: ignore[method-assign]

    logger.info("Starting luxd on %s:%d", host, port)
    server.run()
    logger.info("luxd stopped")


_LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def main() -> None:
    """Entry point for the luxd binary."""
    import argparse

    raw_level = os.environ.get("LUX_LOG_LEVEL", "DEBUG").upper()
    log_level = _LOG_LEVELS.get(raw_level)
    if log_level is None:
        import sys

        print(  # noqa: T201 — before basicConfig, logging unavailable
            f"WARNING: LUX_LOG_LEVEL={raw_level!r} is not valid, defaulting to DEBUG",
            file=sys.stderr,
        )
        log_level = logging.DEBUG
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Lux session hub daemon")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_HUB_PORT, help="Bind port")
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
