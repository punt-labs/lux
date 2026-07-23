"""Integration tests for punt_lux.mcp_transport -- a real streamable-HTTP session.

These drive luxd's assembled app over a real uvicorn port with the mcp SDK
streamable-HTTP client, proving every session capability survives the transport
swap: per-session identity, the full tool surface, pub-sub inbox delivery, and
the disconnect cascade (the live session count returns to zero on close).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections.abc import Generator
from contextlib import AsyncExitStack, contextmanager

import anyio
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from punt_lux.luxd import build_app
from punt_lux.mcp_transport import SESSION_IDLE_TIMEOUT_SECONDS, McpHttpTransport

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


def _health_sessions(port: int) -> int:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
        return int(json.loads(resp.read())["sessions"])


def test_full_session_capabilities_over_streamable_http() -> None:
    """Initialize, list tools, read scenes, and round-trip a business event."""

    async def _drive(port: int) -> dict[str, object]:
        url = f"http://127.0.0.1:{port}/mcp?session_key=itest"
        async with (
            streamable_http_client(url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            scenes = await session.call_tool("list_scenes", {})
            await session.call_tool("subscribe", {"topic": "itest.topic"})
            await session.call_tool(
                "publish", {"topic": "itest.topic", "payload": {"n": 1}}
            )
            received = await session.call_tool("recv", {})
            block = received.content[0]
            return {
                "tool_count": len(tools.tools),
                "scenes_error": scenes.isError,
                "recv": block.text if isinstance(block, TextContent) else "",
                "sessions_during": _health_sessions(port),
            }

    with _running_luxd() as port:
        result = anyio.run(_drive, port)
        # The client context has exited, so the disconnect cascade has run.
        time.sleep(0.3)
        sessions_after = _health_sessions(port)

    assert result["tool_count"] == 27
    assert result["scenes_error"] is False
    assert result["recv"] == 'event:itest.topic:{"n": 1}'
    assert result["sessions_during"] == 1
    assert sessions_after == 0


def test_transport_wires_the_recommended_idle_timeout() -> None:
    """McpHttpTransport hands the SDK manager the module's idle-timeout constant."""
    transport = McpHttpTransport()
    assert transport._manager.session_idle_timeout == SESSION_IDLE_TIMEOUT_SECONDS


def test_idle_session_is_reaped_and_runs_the_disconnect_cascade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session left idle past the timeout is reaped, running the full cascade.

    The client stays connected but sends nothing, so only the SDK's idle timer
    can end the session. Reaping cancels ``SessionScopedServer.run``, whose
    ``finally`` both drops the registry entry (the count this asserts) and runs
    the disconnect cascade via :class:`SessionCleanup`.
    """
    monkeypatch.setattr("punt_lux.mcp_transport.SESSION_IDLE_TIMEOUT_SECONDS", 0.5)

    async def _drive(port: int) -> tuple[int, int]:
        url = f"http://127.0.0.1:{port}/mcp?session_key=idle"
        async with (
            streamable_http_client(url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            during = _health_sessions(port)
            after = during
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                await anyio.sleep(0.1)
                after = _health_sessions(port)
                if after == 0:
                    break
            return during, after

    with _running_luxd() as port:
        during, after = anyio.run(_drive, port)

    assert during == 1
    assert after == 0


def _tool_text(result: CallToolResult) -> str:
    block = result.content[0] if result.content else None
    return block.text if isinstance(block, TextContent) else ""


def test_two_concurrent_sessions_are_isolated() -> None:
    """Two live sessions keep separate identity, inboxes, and lifecycles.

    Each session subscribes to the same topic and publishes its own payload;
    connection-scoped pub-sub means each ``recv`` returns only its own event,
    never the peer's. The live count reflects both, and closing one leaves the
    other fully working with the count down to one.
    """

    async def _drive(port: int) -> tuple[int, str, str, int, bool]:
        url_a = f"http://127.0.0.1:{port}/mcp?session_key=alpha"
        url_b = f"http://127.0.0.1:{port}/mcp?session_key=beta"
        topic = "shared.topic"
        async with (
            streamable_http_client(url_b) as (read_b, write_b, _),
            ClientSession(read_b, write_b) as session_b,
        ):
            await session_b.initialize()
            a_scope = AsyncExitStack()
            read_a, write_a, _ = await a_scope.enter_async_context(
                streamable_http_client(url_a)
            )
            session_a = await a_scope.enter_async_context(
                ClientSession(read_a, write_a)
            )
            await session_a.initialize()

            both_live = _health_sessions(port)

            for session in (session_a, session_b):
                await session.call_tool("subscribe", {"topic": topic})
            await session_a.call_tool(
                "publish", {"topic": topic, "payload": {"who": "A"}}
            )
            await session_b.call_tool(
                "publish", {"topic": topic, "payload": {"who": "B"}}
            )
            a_recv = _tool_text(await session_a.call_tool("recv", {}))
            b_recv = _tool_text(await session_b.call_tool("recv", {}))

            await a_scope.aclose()  # close A only; B stays live

            deadline = time.monotonic() + 8
            after_a_close = both_live
            while time.monotonic() < deadline:
                after_a_close = _health_sessions(port)
                if after_a_close == 1:
                    break
                await anyio.sleep(0.1)

            b_still_works = not (await session_b.call_tool("list_scenes", {})).isError
            return both_live, a_recv, b_recv, after_a_close, b_still_works

    with _running_luxd() as port:
        both_live, a_recv, b_recv, after_a_close, b_still_works = anyio.run(
            _drive, port
        )

    assert both_live == 2
    # Each session received only its own event — connection-scoped isolation.
    assert '"who": "A"' in a_recv
    assert '"who": "B"' not in a_recv
    assert '"who": "B"' in b_recv
    assert '"who": "A"' not in b_recv
    assert after_a_close == 1
    assert b_still_works is True
