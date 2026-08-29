"""End-to-end: hold the listen leg, register on it, receive the click on it.

Runs the real assembled luxd app (REST + the ``/ws`` listen leg) on an ephemeral
loopback port, then drives the full persistent-leg loop with the shipped clients:
a :class:`LuxHubClient` holds the listen connection and registers a menu callback
over REST from its ``on_connect``, a Hub-side click is routed, and the click
arrives at the app handler in the client process. No display is involved.

The order is the contract, not an accident of the test. Registering is refused
unless the calling connection already holds the leg, because a click is delivered
by push and a caller with no leg could never learn of it — which is why
``on_connect`` (the hook that fires after every handshake) is where an app
registers. The last case pins that refusal on the production path.

The middle case is the same loop for a client that does not percent-encode its
identity headers — every released punt-lux, and any third-party client. Its
non-ASCII name reaches the Hub as different bytes on each transport, so it is the
case that proves the Hub reconciles them rather than binding one identity to two
connections.
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

from punt_lux.client._rest_transport import _RestTransport
from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.replicator_instance import hub_callback_router
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.header_value import HeaderValue
from punt_lux.hub_client import LuxHubClient
from punt_lux.luxd import build_app
from punt_lux.operations import Ok, OpError
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


async def _drive(
    client: LuxHubClient, received: list[str], registered: list[object], conn: str
) -> None:
    """Listen, wait for the registration, route a click, assert it arrives."""
    listen = asyncio.create_task(client.listen())
    try:
        await _until(lambda: bool(registered))  # handshake, listener, on_connect
        assert isinstance(registered[0], Ok)  # the leg was held when it registered
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


def test_register_from_on_connect_then_receive_the_click_over_the_websocket() -> None:
    identity = ClientIdentity(kind="app", name=f"voxd-e2e-{os.getpid()}", repo="/w/vox")
    conn = connection_for({"kind": "app", "name": identity.name, "repo": "/w/vox"})
    with _running_luxd() as port:
        rest = _RestTransport(LoopbackTransport(port, 5.0), identity)
        received: list[str] = []
        registered: list[object] = []
        client = LuxHubClient(
            f"ws://127.0.0.1:{port}/ws",
            identity,
            on_callback=received.append,
            on_event=_noop_event,
            # The app's register-fresh work, run after every handshake — by which
            # point the Hub has this connection's listener, so the gate is met.
            on_connect=lambda: registered.append(
                rest.register_callback("beads", "Beads")
            ),
        )
        asyncio.run(_drive(client, received, registered, conn))


@pytest.mark.parametrize("encodes", [True, False])
def test_a_non_ascii_name_registers_on_its_own_leg_from_either_client_generation(
    monkeypatch: pytest.MonkeyPatch, *, encodes: bool
) -> None:
    """Both real transports, a non-ASCII name, both generations of client.

    Driven through the shipped clients and the real header codecs rather than
    reasoned about. A current client percent-encodes its identity, so it crosses as
    ASCII; a client on a released punt-lux sends it raw, and then ``http.client``
    puts the name on the wire as latin-1 while ``websockets`` puts it there as
    UTF-8. Left unreconciled, the second case makes the Hub read two names, bind the
    listen leg to one connection and the REST call to another, and refuse the
    registration for holding no listen leg — the failure the z-spec session hit,
    with nothing in either log naming the cause. Suppressing the encoding is what
    makes this client an older one; both generations must reach one connection.
    """

    def raw(value: HeaderValue) -> str:
        return value.text

    if not encodes:
        monkeypatch.setattr(HeaderValue, "to_wire", raw)
    # The two generations run as two sessions, so they carry two names.
    generation = "encoded" if encodes else "raw"
    identity = ClientIdentity(
        kind="app",
        name=f"z-spec · lux · #{os.getpid():x} · {generation}",
        lease_ttl=30,
    )
    with _running_luxd() as port:
        rest = _RestTransport(LoopbackTransport(port, 5.0), identity)
        registered: list[object] = []
        client = LuxHubClient(
            f"ws://127.0.0.1:{port}/ws",
            identity,
            on_callback=lambda _callback_id: None,
            on_event=_noop_event,
            on_connect=lambda: registered.append(
                rest.register_callback("zspec", "Z-Spec")
            ),
        )
        asyncio.run(_registers(client, registered))
    assert isinstance(registered[0], Ok)


async def _registers(client: LuxHubClient, registered: list[object]) -> None:
    """Hold the leg until ``on_connect`` has reported its registration."""
    listen = asyncio.create_task(client.listen())
    try:
        await _until(lambda: bool(registered))
    finally:
        client.stop()
        listen.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listen


def test_registering_without_the_leg_is_refused_on_the_production_path() -> None:
    """A REST caller holding no listen leg is refused, naming what it must hold."""
    identity = ClientIdentity(kind="app", name=f"legless-{os.getpid()}", repo="/w/vox")
    with _running_luxd() as port:
        result = _RestTransport(
            LoopbackTransport(port, 5.0), identity
        ).register_callback("beads", "Beads")
    assert isinstance(result, OpError)
    assert result.code == "push_required"
    assert "listen leg" in result.reason
