"""Drive a direct streamable-HTTP MCP session against a running luxd.

This is the evidence that Claude Code can reach luxd natively over HTTP MCP,
with no mcp-proxy in the path. Start luxd (``lux hub-install`` then the service,
or ``luxd`` in a terminal), then run::

    uv run python scripts/direct_connection_probe.py

It connects to ``http://127.0.0.1:<port>/mcp`` — the same endpoint Claude Code's
HTTP MCP config points at — initializes a session, lists the tool surface, and
calls a read-only tool, printing a transcript. Exit code 0 means the direct
connection works end to end.
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from punt_lux.hub_paths import HubPaths


async def _probe(url: str) -> int:
    print(f"connecting: {url}")
    async with (
        streamable_http_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        info = await session.initialize()
        print(f"initialized: server={info.serverInfo.name} v{info.serverInfo.version}")

        tools = await session.list_tools()
        print(f"tools: {len(tools.tools)} available")

        scenes = await session.call_tool("list_scenes", {})
        block = scenes.content[0] if scenes.content else None
        payload = block.text if isinstance(block, TextContent) else "<non-text>"
        print(f"list_scenes: isError={scenes.isError} content={payload}")

    print("direct connection OK")
    return 0


def main() -> int:
    port = HubPaths().read_port()
    if port is None:
        print(
            "luxd is not running (no port file). Start it first, e.g. "
            "`lux hub-install` then start the service, or run `luxd`.",
            file=sys.stderr,
        )
        return 1
    return asyncio.run(_probe(f"http://127.0.0.1:{port}/mcp?session_key=probe"))


if __name__ == "__main__":
    raise SystemExit(main())
