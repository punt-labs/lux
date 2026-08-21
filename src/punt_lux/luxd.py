"""luxd — the Lux daemon process entry point.

Boots the session hub: it serves MCP over streamable HTTP at ``/mcp`` beside the
typed REST API on one FastAPI app and uvicorn port, multiplexing MCP sessions
(one per client, keyed by ``?session_key=``) onto a single display connection.
Domain state lives in ``punt_lux.domain.hub``; this module bootstraps transport.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from socket import socket
from typing import TYPE_CHECKING

import uvicorn

if TYPE_CHECKING:
    from punt_lux.domain.hub.expiry_sweep import ExpirySweep
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from punt_lux.log_level import level_from_env
from punt_lux.mcp_transport import McpHttpTransport
from punt_lux.proctitle import set_process_title
from punt_lux.rest import HubHealth, RestSurface
from punt_lux.transport_policy import LoopbackTransportPolicy
from punt_lux.ws_transport import HubListenTransport

logger = logging.getLogger(__name__)

DEFAULT_HUB_PORT = 8430


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def build_app(
    *,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    """Build the FastAPI application luxd serves.

    A factory so tests can construct the app without uvicorn, via ``TestClient``.
    The streamable-HTTP MCP leg, the typed REST surface, and the persistent
    WebSocket listen leg (``/ws``) all mount beside each other on one app.

    The caller's lifespan (replicator, port file) is the outer scope on purpose:
    the inner transport scope unwinds first on shutdown, so a session's cleanup
    cascade still reaches the display through the caller's still-live replicator.
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


# ---------------------------------------------------------------------------
# Port file helpers
# ---------------------------------------------------------------------------


def _write_port_file(port_path: Path, port: int) -> None:
    port_path.parent.mkdir(parents=True, exist_ok=True)
    port_path.write_text(str(port))
    logger.info("Wrote port file: %s (port %d)", port_path, port)


def _remove_port_file(port_path: Path) -> None:
    try:
        port_path.unlink(missing_ok=True)
        logger.info("Removed port file: %s", port_path)
    except OSError:
        logger.warning("Could not remove port file: %s", port_path)


@asynccontextmanager
async def _expiry_sweep_running(
    sweep: ExpirySweep,
) -> AsyncGenerator[asyncio.Task[None]]:
    """Run the frame-TTL sweep for the block, cancelled and awaited on exit.

    On exit the task is cancelled and awaited so none survives shutdown. A task
    that died with an exception re-raises it on await; that is logged and swallowed
    here so the caller's own shutdown always continues (``CancelledError`` from the
    normal cancel is expected and ignored).
    """
    task = asyncio.create_task(sweep.run())
    try:
        yield task
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("frame-expiry sweep task failed before shutdown")


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def serve(
    host: str = "127.0.0.1",
    port: int = DEFAULT_HUB_PORT,
) -> None:
    """Start the luxd hub. Blocks until shutdown.

    A non-loopback ``host`` is refused before any bind: luxd is loopback-only
    until authentication and a bind-derived origin policy exist, so it fails
    fast with one line rather than binding a wider interface than its transport
    guards trust.
    """
    if not LoopbackTransportPolicy().allows_bind_host(host):
        print(  # noqa: T201 — startup refusal must reach the operator's console
            f"luxd refuses to bind non-loopback host {host!r}: it is loopback-only "
            "until authentication lands. Bind 127.0.0.1 or localhost.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    from punt_lux.hub_paths import HubPaths

    hub_paths = HubPaths()
    pid_path = hub_paths.pid_path
    port_path = hub_paths.port_path

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        # The display-connection workers and the frame-TTL sweep start and stop
        # with luxd. Imported lazily to keep the Hub singletons out of module import.
        from punt_lux.domain.hub import hub_display
        from punt_lux.domain.hub.display_workers import display_workers
        from punt_lux.domain.hub.expiry_sweep import ExpirySweep

        display_workers.start()
        sweep = ExpirySweep(hub_display.frames, display_workers.replicator)
        try:
            # The sweep is cancelled and awaited when this block exits — before the
            # replicator stops — so no pending task survives shutdown.
            async with _expiry_sweep_running(sweep):
                yield
        finally:
            display_workers.stop()
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


def main() -> None:
    """Boot luxd — DEBUG floor so launchd's stderr log stays readable."""
    logging.basicConfig(
        level=level_from_env("DEBUG"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    set_process_title("luxd-hub")
    parser = argparse.ArgumentParser(description="Lux session hub daemon")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_HUB_PORT, help="Bind port")
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
