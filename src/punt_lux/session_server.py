"""SessionServer — the process one Claude Code session runs: MCP surface and leg.

``lux mcp-serve`` starts this and nothing else. It is two things that must live in
one process: the stdio MCP endpoint the session talks to, and the live connection
to luxd that services the session's menu clicks. They are together because the
second is why the process exists — a menu entry must launch in the time a user
reads as instant, so something that is always there and always reachable has to
own it — and once a session has such a process, that process is also where its
MCP traffic belongs.

The two halves do not share state. The leg runs on its own thread with its own
clients; the proxy runs on the main thread and forwards bytes. Their only relation
is the identity they were both built from, which is what makes luxd treat them as
one session's two legs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.beads_service import BeadsService
from punt_lux.session_identity import SessionIdentity
from punt_lux.session_proxy import StdioHubProxy
from punt_lux.session_service import SessionCallbackLeg

if TYPE_CHECKING:
    from punt_lux.session_service import SessionService

__all__ = ["SessionServer"]


@final
class SessionServer:
    """One session's process: start its servicing leg, then serve its MCP surface."""

    _identity: SessionIdentity
    _service: SessionService
    __slots__ = ("_identity", "_service")

    def __new__(cls, identity: SessionIdentity, service: SessionService) -> Self:
        self = super().__new__(cls)
        self._identity = identity
        self._service = service
        return self

    @classmethod
    def for_cwd(cls) -> Self:
        """Build the server for the repository this session was started in."""
        return cls(SessionIdentity.resolve(), BeadsService.for_repo())

    def serve(self) -> None:
        """Run until the session ends — when Claude Code closes this process's stdin.

        The leg is started first and never waited on: it is a daemon thread that
        connects, registers, and retries on its own, so a Hub that is slow to come
        up delays the session's menu entry and nothing else. The proxy then holds
        the main thread for the life of the session.
        """
        SessionCallbackLeg(self._identity.client, self._service).start()
        StdioHubProxy.for_session(self._identity.mcp_session_key).serve()
