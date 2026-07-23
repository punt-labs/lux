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
from contextlib import contextmanager

import anyio
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from punt_lux.luxd import build_app

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
