"""StdioHubProxy — a session's MCP surface is luxd's, carried and not reshaped.

A real MCP client is wired to the proxy over in-memory streams while the Hub end
is entirely real: the assembled luxd app on an ephemeral loopback port. So what
these assert is what a session gets — the same handshake, the same tool roster,
the same tool results as talking to luxd directly — and that the conduit ends when
the client's side of it does, which is how a session says it is over.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

import anyio
import pytest
import uvicorn
from mcp import ClientSession
from mcp.types import TextContent

from punt_lux.hub_paths import HubPaths
from punt_lux.luxd import build_app
from punt_lux.rest_transport import HubUnavailableError
from punt_lux.session_proxy import StdioHubProxy

if TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from mcp.shared.message import SessionMessage

pytestmark = pytest.mark.integration

# A sample of the roster that must arrive unchanged: the universal render API, a
# read, and the session's own callback registration. Asserting a subset rather
# than the whole set keeps this about transparency — the roster itself is pinned
# once, in the transport's own canary.
_EXPECTED_SAMPLE = frozenset({"show", "list_scenes", "register_callback", "identify"})

# The first thing any MCP client sends, used to prove the shipped process answers.
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "session-proxy-test", "version": "0"},
    },
}


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


def _proxy(port: int, session_key: str) -> StdioHubProxy:
    return StdioHubProxy(f"http://127.0.0.1:{port}/mcp?session_key={session_key}")


def _client_streams() -> tuple[
    MemoryObjectSendStream[SessionMessage],
    MemoryObjectReceiveStream[SessionMessage | Exception],
    MemoryObjectSendStream[SessionMessage],
    MemoryObjectReceiveStream[SessionMessage | Exception],
]:
    """Two pipes standing in for stdin and stdout: client→proxy and proxy→client."""
    to_proxy, from_client = anyio.create_memory_object_stream["SessionMessage"](0)
    to_client, from_proxy = anyio.create_memory_object_stream["SessionMessage"](0)
    return (
        to_proxy,
        cast("MemoryObjectReceiveStream[SessionMessage | Exception]", from_client),
        to_client,
        cast("MemoryObjectReceiveStream[SessionMessage | Exception]", from_proxy),
    )


def test_a_session_sees_luxds_own_tool_surface_through_the_proxy() -> None:
    """Initialize, list tools, and call one — none of it touched on the way."""

    async def _drive(port: int) -> tuple[frozenset[str], str]:
        to_proxy, from_client, to_client, from_proxy = _client_streams()
        # Seeded so a block that never ran fails the assertions rather than the
        # name lookup — an empty roster satisfies nothing.
        names: frozenset[str] = frozenset()
        event = ""
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_proxy(port, "proxy-itest").pump, from_client, to_client)
            async with ClientSession(from_proxy, to_proxy) as session:
                await session.initialize()
                tools = await session.list_tools()
                await session.call_tool("subscribe", {"topic": "proxy.itest"})
                await session.call_tool(
                    "publish", {"topic": "proxy.itest", "payload": {"n": 1}}
                )
                received = await session.call_tool("recv", {})
                block = received.content[0]
                names = frozenset(tool.name for tool in tools.tools)
                event = block.text if isinstance(block, TextContent) else ""
            tasks.cancel_scope.cancel()
        return names, event

    with _running_luxd() as port:
        names, event = anyio.run(_drive, port)

    assert names >= _EXPECTED_SAMPLE
    # A tool result crosses back verbatim, payload and all.
    assert event == 'event:proxy.itest:{"n": 1}'


def test_the_conduit_ends_when_the_client_side_closes() -> None:
    """Closing the client's stream is how a session ends; the pump must return.

    In the shipped process that stream is stdin, so this is what makes ``lux
    mcp-serve`` exit when Claude Code closes the session rather than lingering.
    """

    async def _drive(port: int) -> bool:
        to_proxy, from_client, to_client, _from_proxy = _client_streams()
        ended = False
        with anyio.fail_after(10):
            async with anyio.create_task_group() as tasks:

                async def _pump() -> None:
                    nonlocal ended
                    await _proxy(port, "proxy-close").pump(from_client, to_client)
                    ended = True

                tasks.start_soon(_pump)
                await anyio.sleep(0.1)
                await to_proxy.aclose()  # the client hung up
        return ended

    with _running_luxd() as port:
        assert anyio.run(_drive, port) is True


def test_the_shipped_process_answers_and_then_exits_with_its_session(
    tmp_path: Path,
) -> None:
    """Drive the real ``lux mcp-serve`` process the way Claude Code does.

    The in-memory case above cannot see this: the stdio transport's own writer
    task has no reason to finish, so a proxy that merely stops forwarding leaves a
    process behind for every session ever opened. Only a real process, with a real
    stdin closed by its parent, proves it goes away.
    """
    with _running_luxd() as port:
        # The process finds luxd through its port file under the home directory,
        # so a temporary home points it at this test's Hub.
        home = tmp_path / "home"
        (home / ".punt-labs" / "lux").mkdir(parents=True)
        (home / ".punt-labs" / "lux" / "hub.port").write_text(str(port))

        proc = subprocess.Popen(
            [sys.executable, "-m", "punt_lux", "mcp-serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "HOME": str(home)},
        )
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None
            proc.stdin.write(json.dumps(_INITIALIZE) + "\n")
            proc.stdin.flush()
            reply = json.loads(proc.stdout.readline())
            proc.stdin.close()
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()

    assert reply["result"]["serverInfo"]["name"] == "lux"  # luxd's own server
    assert proc.returncode == 0  # and it left when the session did


def test_a_hub_that_never_appears_is_named_not_hung_on() -> None:
    """With no port file the proxy refuses to start, naming the fix."""
    original = HubPaths.read_port
    try:
        HubPaths.read_port = lambda _self: None  # type: ignore[method-assign, assignment]  # absent-Hub stand-in
        with pytest.raises(HubUnavailableError, match="hub-install"):
            StdioHubProxy.for_session("nobody", wait=0.05)
    finally:
        HubPaths.read_port = original  # type: ignore[method-assign]  # restore the real read


def test_the_session_key_reaches_luxd_as_this_sessions_connection() -> None:
    """Every request in a session lands on one Hub connection, not one per call."""

    async def _drive(port: int) -> str:
        to_proxy, from_client, to_client, from_proxy = _client_streams()
        clients = ""
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_proxy(port, "proxy-key").pump, from_client, to_client)
            async with ClientSession(from_proxy, to_proxy) as session:
                await session.initialize()
                await session.call_tool(
                    "identify",
                    {"kind": "mcp-session", "name": "proxy-key", "repo": "/w/lux"},
                )
                listed = await session.call_tool("list_clients", {})
                block = listed.content[0]
                clients = block.text if isinstance(block, TextContent) else ""
            tasks.cancel_scope.cancel()
        return clients

    with _running_luxd() as port:
        clients = anyio.run(_drive, port)

    # The identity declared on one call is the identity the next call's session
    # still has — which only holds if both landed on the same connection.
    assert "proxy-key" in clients
