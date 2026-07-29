"""End-to-end: register a callback over REST, receive its click over the WebSocket.

Runs the real assembled luxd app (REST + the ``/ws`` listen leg) on an ephemeral
loopback port, then drives the full persistent-leg loop with the shipped clients:
a :class:`LuxRestClient` registers a menu callback, a :class:`LuxHubClient` holds
the listen connection, a Hub-side click is routed, and the click arrives at the
app handler in the client process. No display is involved.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager

import anyio
import pytest
import uvicorn

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.replicator_instance import hub_callback_router
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.hub_client import LuxHubClient
from punt_lux.luxd import build_app
from punt_lux.operations import Ok
from punt_lux.rest_client import LuxRestClient
from punt_lux.rest_loopback import LoopbackTransport

pytestmark = pytest.mark.integration


@contextmanager
def _running_luxd() -> Generator[int]:
    """Serve the assembled app on an ephemeral loopback port; yield the port."""
    config = uvicorn.Config(build_app(), host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: anyio.run(server.serve), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not server.started:
            raise RuntimeError("luxd did not start within 10s")
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _noop_event(_topic: str, _payload: Mapping[str, object]) -> None:
    return None


async def _until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached within timeout")


async def _drive(client: LuxHubClient, received: list[str], conn: str) -> None:
    """Listen, wait for the handshake, route a click Hub-side, assert it arrives."""
    listen = asyncio.create_task(client.listen())
    try:
        await _until(lambda: client.connection_id != "")  # handshake + listener wired
        outcome = hub_callback_router.route(
            CallbackInvocation(conn, "beads")  # type: ignore[arg-type]  # ConnectionId is a str NewType
        )
        assert outcome == "routed"
        await _until(lambda: received == ["beads"])
    finally:
        client.stop()
        listen.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listen


def test_register_over_rest_then_receive_the_click_over_the_websocket() -> None:
    identity = ClientIdentity(kind="app", name=f"voxd-e2e-{os.getpid()}", repo="/w/vox")
    conn = connection_for({"kind": "app", "name": identity.name, "repo": "/w/vox"})
    with _running_luxd() as port:
        rest = LuxRestClient(LoopbackTransport(port, 5.0), identity)
        assert isinstance(rest.register_callback("beads", "Beads"), Ok)

        received: list[str] = []
        client = LuxHubClient(
            f"ws://127.0.0.1:{port}/ws",
            identity,
            on_callback=received.append,
            on_event=_noop_event,
        )
        asyncio.run(_drive(client, received, conn))
