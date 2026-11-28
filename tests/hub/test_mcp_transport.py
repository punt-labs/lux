"""Integration tests for punt_lux.hub.mcp_transport -- a real streamable-HTTP session.

These drive luxd's assembled app over a real uvicorn port with the mcp SDK
streamable-HTTP client, proving every session capability survives the transport
swap: per-session identity, the full tool surface, pub-sub inbox delivery, and
the disconnect cascade (the live session count returns to zero on close).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request
from collections.abc import Generator
from contextlib import AsyncExitStack, contextmanager
from pathlib import Path

import anyio
import httpx
import pytest
import uvicorn
from fastmcp import Client
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import UNSUPPORTED_PROTOCOL_VERSION, CallToolResult, TextContent
from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY
from mcp_types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_HANDSHAKE_VERSION,
    LATEST_MODERN_VERSION,
)

from punt_lux.hub.luxd import build_app
from punt_lux.hub.mcp_transport import SESSION_IDLE_TIMEOUT_SECONDS, McpHttpTransport
from punt_lux.service.repo_activation import SHARED

pytestmark = pytest.mark.integration

# The full MCP tool roster the transport must expose over the wire. Pinned
# explicitly (not derived from ``tools.__all__``) so adding or removing a tool
# trips this test on purpose; comparing the roster as a set means the failure
# names the exact tool that changed rather than only a count that moved.
_EXPECTED_TOOLS = frozenset(
    {
        "callback_pending",
        "callback_register",
        "display_info",
        "display_link_get",
        "display_mode_get",
        "display_screenshot",
        "display_state_get",
        "display_theme_get",
        "display_window_get",
        "enablement",
        "error_ls",
        "event_ls",
        "frame_remove",
        "list_frames",
        "menu_ls",
        "menu_set",
        "ping",
        "scene_clear",
        "scene_clear_all",
        "scene_dashboard",
        "scene_inspect",
        "scene_ls",
        "scene_show",
        "scene_table",
        "scene_update",
        "session_identify",
        "session_ls",
        "status",
        "topic_publish",
        "topic_recv",
        "topic_subscribe",
        "topic_unsubscribe",
    }
)


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
            streamable_http_client(url) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            scenes = await session.call_tool("scene_ls", {})
            await session.call_tool("topic_subscribe", {"topic": "itest.topic"})
            await session.call_tool(
                "topic_publish", {"topic": "itest.topic", "payload": {"n": 1}}
            )
            received = await session.call_tool("topic_recv", {})
            block = received.content[0]
            return {
                "tool_names": frozenset(tool.name for tool in tools.tools),
                "scenes_error": scenes.is_error,
                "recv": block.text if isinstance(block, TextContent) else "",
                "sessions_during": _health_sessions(port),
            }

    with _running_luxd() as port:
        result = anyio.run(_drive, port)
        # The client context has exited, so the disconnect cascade has run.
        time.sleep(0.3)
        sessions_after = _health_sessions(port)

    # Set equality, so a drift fails naming the exact tool added or removed.
    assert result["tool_names"] == _EXPECTED_TOOLS
    assert result["scenes_error"] is False
    assert result["recv"] == 'event:itest.topic:{"n": 1}'
    assert result["sessions_during"] == 1
    assert sessions_after == 0


def test_auto_negotiation_keeps_http_stateful() -> None:
    """A FastMCP 4 client falls back to the persistent session protocol."""

    async def _drive(port: int) -> None:
        async with Client(f"http://127.0.0.1:{port}/mcp?session_key=auto") as client:
            assert _health_sessions(port) == 1
            assert not (await client.call_tool_mcp("scene_ls", {})).is_error

    with _running_luxd() as port:
        anyio.run(_drive, port)


def test_sessionless_discovery_requires_a_stateful_handshake() -> None:
    """A modern request gets the supported handshake versions, not a session."""
    with _running_luxd() as port:
        response = httpx.post(
            f"http://127.0.0.1:{port}/mcp?session_key=sessionless",
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": LATEST_MODERN_VERSION,
                "Mcp-Method": "server/discover",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {
                    "_meta": {
                        PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
                        CLIENT_CAPABILITIES_META_KEY: {},
                    }
                },
            },
            timeout=5,
        )
        assert response.status_code == 400, response.text
        error = response.json()["error"]
        assert error["code"] == UNSUPPORTED_PROTOCOL_VERSION
        assert set(error["data"]["supported"]) == set(HANDSHAKE_PROTOCOL_VERSIONS)
        assert "mcp-session-id" not in response.headers
        assert _health_sessions(port) == 0


def test_transport_wires_the_recommended_idle_timeout() -> None:
    """McpHttpTransport hands the SDK manager the module's idle-timeout constant."""
    transport = McpHttpTransport()
    assert transport._manager._sdk.session_idle_timeout == SESSION_IDLE_TIMEOUT_SECONDS


def _open_session_without_get_stream(url: str) -> None:
    """Initialize an MCP session over plain POSTs, then go silent.

    The SDK client keeps a standalone GET stream open, and an open GET stream
    counts as activity for the session manager's idle timer (mcp >= 1.30), so
    it would hold the session alive. This models a client that vanished after
    its last request instead: no request in flight, nothing left open.
    """
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_HANDSHAKE_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "idle-test", "version": "0"},
        },
    }
    with httpx.Client(timeout=5) as client:
        response = client.post(url, json=initialize, headers=headers)
        response.raise_for_status()
        headers["mcp-session-id"] = response.headers["mcp-session-id"]
        headers["mcp-protocol-version"] = LATEST_HANDSHAKE_VERSION
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        client.post(url, json=initialized, headers=headers).raise_for_status()


def test_idle_session_is_reaped_and_runs_the_disconnect_cascade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session left idle past the timeout is reaped, running the full cascade.

    The client initializes and then sends nothing, so only the SDK's idle timer
    can end the session. The SDK's connection exit stack drops the registry
    entry and runs the disconnect cascade.
    """
    monkeypatch.setattr("punt_lux.hub.mcp_transport.SESSION_IDLE_TIMEOUT_SECONDS", 0.5)

    with _running_luxd() as port:
        _open_session_without_get_stream(
            f"http://127.0.0.1:{port}/mcp?session_key=idle"
        )
        during = _health_sessions(port)
        after = during
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            time.sleep(0.1)
            after = _health_sessions(port)
            if after == 0:
                break

    assert during == 1
    assert after == 0


def _tool_text(result: CallToolResult) -> str:
    block = result.content[0] if result.content else None
    return block.text if isinstance(block, TextContent) else ""


def test_repo_less_scene_calls_follow_advertised_checkout(tmp_path: Path) -> None:
    """HTTP roots discovery binds repo-less scene calls to the advertised checkout."""
    subprocess.run(
        ["/usr/bin/env", "git", "init", "--quiet", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    marker = tmp_path / SHARED / "enabled"

    async def _drive(port: int) -> None:
        url = f"http://127.0.0.1:{port}/mcp"
        async with Client(url, roots=[tmp_path.as_uri()]) as client:
            dormant = await client.call_tool_mcp("scene_ls", {})
            assert dormant.is_error
            assert "Run /lux enable" in _tool_text(dormant)
            assert str(marker) in _tool_text(dormant)
            marker.parent.mkdir(parents=True)
            marker.touch()
            assert not (await client.call_tool_mcp("scene_ls", {})).is_error
            marker.unlink()
            assert (await client.call_tool_mcp("scene_ls", {})).is_error

    with _running_luxd() as port:
        anyio.run(_drive, port)


def test_advertised_checkout_stays_dormant_with_another_repo_declared(
    tmp_path: Path,
) -> None:
    invoking = tmp_path / "invoking"
    other = tmp_path / "other"
    for repo in (invoking, other):
        subprocess.run(
            ["/usr/bin/env", "git", "init", "--quiet", str(repo)],
            check=True,
            capture_output=True,
        )
    other_marker = other / SHARED / "enabled"
    other_marker.parent.mkdir(parents=True)
    other_marker.touch()
    invoking_marker = invoking / SHARED / "enabled"
    identify = {"kind": "mcp-session", "name": "cross-checkout", "repo": str(other)}

    async def _drive(port: int) -> None:
        url = f"http://127.0.0.1:{port}/mcp"
        async with Client(url, roots=[invoking.as_uri()]) as client:
            dormant = await client.call_tool_mcp("session_identify", identify)
            assert dormant.is_error
            assert str(invoking_marker) in _tool_text(dormant)
            invoking_marker.parent.mkdir(parents=True)
            invoking_marker.touch()
            assert not (
                await client.call_tool_mcp("session_identify", identify)
            ).is_error
            assert not (await client.call_tool_mcp("scene_ls", {})).is_error
            invoking_marker.unlink()
            dormant = await client.call_tool_mcp("scene_ls", {})
            assert dormant.is_error
            assert str(invoking_marker) in _tool_text(dormant)

    with _running_luxd() as port:
        anyio.run(_drive, port)


def test_declared_checkout_can_select_a_later_advertised_root(tmp_path: Path) -> None:
    off = tmp_path / "off"
    on = tmp_path / "on"
    for repo in (off, on):
        subprocess.run(
            ["/usr/bin/env", "git", "init", "--quiet", str(repo)],
            check=True,
            capture_output=True,
        )
    off_marker = off / SHARED / "enabled"
    on_marker = on / SHARED / "enabled"
    on_marker.parent.mkdir(parents=True)
    on_marker.touch()

    async def _drive(port: int) -> None:
        url = f"http://127.0.0.1:{port}/mcp"
        async with Client(url, roots=[off.as_uri(), on.as_uri()]) as client:
            dormant = await client.call_tool_mcp("scene_ls", {})
            assert dormant.is_error
            assert str(off_marker) in _tool_text(dormant)
            identified = await client.call_tool_mcp(
                "session_identify",
                {"kind": "mcp-session", "name": "second-root", "repo": str(on)},
            )
            assert _tool_text(identified) == "identified:second-root"
            assert not (await client.call_tool_mcp("scene_ls", {})).is_error
            on_marker.unlink()
            dormant = await client.call_tool_mcp("scene_ls", {})
            assert dormant.is_error
            assert str(on_marker) in _tool_text(dormant)
            dormant = await client.call_tool_mcp("scene_ls", {})
            assert dormant.is_error
            assert str(on_marker) in _tool_text(dormant)
            on_marker.touch()
            assert not (await client.call_tool_mcp("scene_ls", {})).is_error

    with _running_luxd() as port:
        anyio.run(_drive, port)


def test_identified_session_can_inspect_and_clear_its_scene() -> None:
    """A session without a query key uses one Hub scope for all its calls."""

    async def _drive(port: int) -> None:
        url = f"http://127.0.0.1:{port}/mcp"
        async with (
            streamable_http_client(url) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            identified = await session.call_tool(
                "session_identify", {"kind": "mcp-session", "name": "scene-roundtrip"}
            )
            assert _tool_text(identified) == "identified:scene-roundtrip"
            shown = await session.call_tool(
                "scene_show",
                {
                    "scene_id": "roundtrip",
                    "elements": [{"kind": "text", "id": "label", "content": "Hello"}],
                },
            )
            assert _tool_text(shown) == "shown:roundtrip"
            listed = await session.call_tool("scene_ls", {})
            scenes = json.loads(_tool_text(listed))["scenes"]
            (scene,) = [scene for scene in scenes if scene["local_id"] == "roundtrip"]
            assert scene["owners"][0]["identity"]["name"] == "scene-roundtrip"

            args = {"scene_id": scene["local_id"]}
            inspected = await session.call_tool("scene_inspect", args)
            detail = json.loads(_tool_text(inspected))
            assert detail["kind"] == "ok", detail
            assert detail["scene_id"] == "roundtrip"
            assert detail["elements"][0]["resolved_props"]["content"] == "Hello"
            cleared = await session.call_tool("scene_clear", args)
            assert _tool_text(cleared) == "cleared"
            listed = await session.call_tool("scene_ls", {})
            assert not any(
                entry["local_id"] == "roundtrip"
                for entry in json.loads(_tool_text(listed))["scenes"]
            )

    with _running_luxd() as port:
        anyio.run(_drive, port)


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
            streamable_http_client(url_b) as (read_b, write_b),
            ClientSession(read_b, write_b) as session_b,
        ):
            await session_b.initialize()
            a_scope = AsyncExitStack()
            read_a, write_a = await a_scope.enter_async_context(
                streamable_http_client(url_a)
            )
            session_a = await a_scope.enter_async_context(
                ClientSession(read_a, write_a)
            )
            await session_a.initialize()

            both_live = _health_sessions(port)

            for session in (session_a, session_b):
                await session.call_tool("topic_subscribe", {"topic": topic})
            await session_a.call_tool(
                "topic_publish", {"topic": topic, "payload": {"who": "A"}}
            )
            await session_b.call_tool(
                "topic_publish", {"topic": topic, "payload": {"who": "B"}}
            )
            a_recv = _tool_text(await session_a.call_tool("topic_recv", {}))
            b_recv = _tool_text(await session_b.call_tool("topic_recv", {}))

            await a_scope.aclose()  # close A only; B stays live

            deadline = time.monotonic() + 8
            after_a_close = both_live
            while time.monotonic() < deadline:
                after_a_close = _health_sessions(port)
                if after_a_close == 1:
                    break
                await anyio.sleep(0.1)

            b_still_works = not (await session_b.call_tool("scene_ls", {})).is_error
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
