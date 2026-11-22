"""luxd — the Lux daemon process entry point.

Boots the session hub: it serves MCP over streamable HTTP at ``/mcp`` beside the
typed REST API on one FastAPI app and uvicorn port, multiplexing MCP sessions
(one per client, keyed by ``?session_key=``) onto a single display connection.
Domain state lives in ``punt_lux.domain.hub``; this module bootstraps transport.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from socket import socket
from typing import Self, final

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from punt_lux.kernel.hub_defaults import DEFAULT_HUB_PORT
from punt_lux.logging_config import process_diagnostics
from punt_lux.mcp_transport import McpHttpTransport
from punt_lux.proctitle import set_process_title
from punt_lux.rest import HubHealth, RestSurface
from punt_lux.transport_policy import LoopbackTransportPolicy
from punt_lux.ws_transport import HubListenTransport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def build_app(
    *,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    """Build the FastAPI application luxd serves.

    A factory so tests can construct the app without uvicorn. The
    streamable-HTTP MCP leg, the typed REST surface, and the persistent
    WebSocket listen leg (``/ws``) all mount beside each other on one app.
    The caller's lifespan is the outer scope, so a session's cleanup
    cascade still reaches the display through the still-live replicator.
    """
    transport = McpHttpTransport()

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if lifespan is None:
            async with transport.lifespan():
                yield
        else:
            async with lifespan(app), transport.lifespan():
                yield

    app = FastAPI(lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost"],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    async def _health_route() -> HubHealth:
        """Report process liveness and the live MCP session count."""
        return HubHealth(sessions=transport.session_count)

    app.add_api_route("/health", _health_route, methods=["GET"])
    transport.mount(app)
    RestSurface.for_hub().mount(app)
    HubListenTransport.for_hub().mount(app)
    return app


@final
class _ServerConfig:
    """What luxd serves with: the app, where it binds, and how uvicorn is set.

    ``proxy_headers`` is off: uvicorn would otherwise rewrite the connection's
    client address from an ``X-Forwarded-For`` header sent by any loopback caller
    (its default trusted proxy), turning a declaration into the "observed" host
    the Hub records. luxd has no reverse proxy in front of it, so the socket peer
    is the only address there is to trust.
    """

    _app: FastAPI
    _host: str
    _port: int
    __slots__ = ("_app", "_host", "_port")

    def __new__(cls, app: FastAPI, host: str, port: int) -> Self:
        self = super().__new__(cls)
        self._app = app
        self._host = host
        self._port = port
        return self

    def config(self) -> uvicorn.Config:
        """Build the uvicorn config for this app and bind."""
        return uvicorn.Config(
            self._app,
            host=self._host,
            port=self._port,
            log_config=None,
            log_level="warning",
            access_log=False,
            proxy_headers=False,
            # Unset, uvicorn waits forever for every open connection to close on
            # SIGTERM -- an MCP streamable-HTTP session is long-lived by design,
            # so a healthy luxd would never exit. Bounded so a restart completes.
            timeout_graceful_shutdown=10,
        )


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def serve(
    host: str = "127.0.0.1",
    port: int = DEFAULT_HUB_PORT,
) -> None:
    """Start the luxd hub. Blocks until shutdown.

    A non-loopback ``host`` is refused before any bind: luxd is loopback-only
    until authentication and a bind-derived origin policy exist.
    """
    if not LoopbackTransportPolicy().allows_bind_host(host):
        logger.warning(
            "luxd refuses to bind a non-loopback host. Bind 127.0.0.1 or localhost."
        )
        raise SystemExit(2)

    from punt_lux.hub_lifespan import HubLifespan
    from punt_lux.kernel.hub_paths import HubPaths

    lifespan = HubLifespan(HubPaths())
    app = build_app(lifespan=lifespan.run)

    config = _ServerConfig(app, host, port).config()
    server = uvicorn.Server(config)

    original_startup = server.startup  # write the port file after the real bind

    async def _startup_with_port_file(
        sockets: list[socket] | None = None,
    ) -> None:
        await original_startup(sockets=sockets)
        if server.servers and server.servers[0].sockets:
            actual_port = server.servers[0].sockets[0].getsockname()[1]
            pid = lifespan.record_listening(actual_port)
            logger.info("luxd listening on %s:%d (pid %d)", host, actual_port, pid)
        else:
            logger.error("Server started but no bound sockets; port file not written")

    server.startup = _startup_with_port_file  # type: ignore[method-assign]

    logger.info("Starting luxd on %s:%d", host, port)
    server.run()
    logger.info("luxd stopped")


def main() -> None:
    """Boot the Hub daemon and its HTTP MCP server with shared diagnostics."""
    parser = argparse.ArgumentParser(description="Lux session hub daemon")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_HUB_PORT, help="Bind port")
    args = parser.parse_args()
    with process_diagnostics("daemon", "luxd-hub"):
        set_process_title("luxd-hub")
        serve(host=args.host, port=args.port)
