"""StdioHubProxy — this session's MCP surface, carried verbatim to luxd and back.

Claude Code speaks MCP to a session over stdio; luxd speaks it over streamable
HTTP. This joins the two and does nothing else: every message is forwarded as it
arrived, in both directions, with no tool logic, no rewriting, and no state of its
own. The tool surface a session sees is therefore exactly luxd's — one engine, one
code path — and adding a tool to luxd adds it here for free.

The proxy exists because the process must be *ours*. A session's menu entry has to
be serviced by something that is always there and always reachable, so the session
runs a process of its own; once it does, that process is also the natural place to
speak MCP from. The forwarding is the cheap half; the leg it runs beside
(:mod:`punt_lux.session_service`) is the half that earns the process.

Both directions end together. When Claude Code closes stdin the session is over,
the pump for that direction finishes, and the whole task group is cancelled — the
HTTP transport's own close then tells luxd the session ended.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING, Self, final
from urllib.parse import quote

import anyio
from mcp.client.streamable_http import streamable_http_client
from mcp.server.stdio import stdio_server

from punt_lux.hub_paths import HubPaths
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from anyio.abc import CancelScope
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

__all__ = ["StdioHubProxy"]

# How long to keep looking for luxd's port before giving up at startup. A session
# can begin while the Hub is still coming up at login, and a session whose tool
# surface is dead for its whole life is a far worse outcome than a slow first
# answer — but the wait must stay well inside the host's own startup budget, and
# when luxd is already up (the normal case) the first read succeeds immediately.
_PORT_WAIT_SECONDS = 5.0
_PORT_POLL_SECONDS = 0.05


@final
class StdioHubProxy:
    """A session's stdio MCP endpoint, forwarding both directions to luxd."""

    _url: str
    __slots__ = ("_url",)

    def __new__(cls, url: str) -> Self:
        self = super().__new__(cls)
        self._url = url
        return self

    @classmethod
    def for_session(cls, session_key: str, *, wait: float = _PORT_WAIT_SECONDS) -> Self:
        """Build the proxy for luxd's current port, or raise if it never appears.

        The session key rides as a query parameter and becomes this session's Hub
        connection, so every request in the session lands on one connection instead
        of a fresh one per call.
        """
        port = cls._await_port(wait)
        return cls(f"http://127.0.0.1:{port}/mcp?session_key={quote(session_key)}")

    @staticmethod
    def _await_port(wait: float) -> int:
        """Return luxd's port, waiting briefly for a Hub that is still starting."""
        paths = HubPaths()
        deadline = time.monotonic() + wait
        while True:
            port = paths.read_port()
            if port is not None:
                return port
            if time.monotonic() >= deadline:
                msg = (
                    "luxd is not running. "
                    "Run 'lux hub-install' to register the service."
                )
                raise HubUnavailableError(msg)
            time.sleep(_PORT_POLL_SECONDS)

    def serve(self) -> None:
        """Forward this process's stdio MCP traffic until the session ends."""
        anyio.run(self._serve_stdio)

    async def _serve_stdio(self) -> None:
        """Bind the client side to this process's stdin and stdout, then pump.

        The stdio transport runs a reader and a writer task of its own, and its
        writer waits on a stream that nothing else ever closes — so leaving its
        scope normally would wait forever for a task that has no reason to finish,
        and the process would outlive the session that started it. Cancelling once
        the pump is done ends both of its tasks, which is what makes ``lux
        mcp-serve`` exit when Claude Code closes stdin.
        """
        with anyio.CancelScope() as transport:
            async with stdio_server() as (from_client, to_client):
                await self.pump(from_client, to_client)
                transport.cancel()

    async def pump(
        self,
        from_client: MemoryObjectReceiveStream[SessionMessage | Exception],
        to_client: MemoryObjectSendStream[SessionMessage],
    ) -> None:
        """Carry a client's MCP conversation to luxd and back until either ends.

        The client's streams are given rather than opened here, so what a session
        actually gets — a transparent conduit to luxd's tool surface — can be driven
        by a real MCP client over a pair of in-memory streams, with the Hub end
        entirely real.
        """
        async with (
            streamable_http_client(self._url) as (from_hub, to_hub, _session_id),
            anyio.create_task_group() as pumps,
        ):
            pumps.start_soon(self._forward, from_client, to_hub, pumps.cancel_scope)
            pumps.start_soon(self._forward, from_hub, to_client, pumps.cancel_scope)

    @staticmethod
    async def _forward(
        source: MemoryObjectReceiveStream[SessionMessage | Exception],
        sink: MemoryObjectSendStream[SessionMessage],
        scope: CancelScope,
    ) -> None:
        """Carry every message from ``source`` to ``sink``, then end the session.

        A message the transport could not read arrives as the exception itself.
        Dropping it is the transparent thing to do: the proxy is not a party to the
        conversation, so it reports the malformed message and leaves the peers'
        own protocol handling — a timeout, a retry, an error reply — to them,
        rather than inventing a reply neither side asked it for.

        Either direction ending ends both. Stdin closing is how a session says it
        is over, and a Hub-side close leaves nothing to forward.
        """
        with contextlib.suppress(anyio.BrokenResourceError, anyio.ClosedResourceError):
            async for message in source:
                if isinstance(message, Exception):
                    logger.warning("dropping an unreadable MCP message: %s", message)
                    continue
                await sink.send(message)
        scope.cancel()
