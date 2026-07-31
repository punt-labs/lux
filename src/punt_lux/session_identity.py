"""SessionIdentity — what one ``lux mcp-serve`` process declares itself to be.

A session server owns two legs into the Hub: the WebSocket it holds open to
receive its menu clicks, and the REST calls it makes to push what those clicks
produce. Both must resolve to one Hub connection, so both declare this identity;
:func:`~punt_lux.connection_identity.connection_for` derives the shared
connection id from its fields.

The name is what a user reads in the menu bar, so it says three things in one
uniform shape — ``lux · <repository> · #<process>``: which tool the entries
belong to, which repository this session works in, and which of possibly several
sessions on that repository it is.

The last part is not cosmetic. Two Claude Code sessions open on the same
repository are two separate services with separate menu entries, and identities
that compared equal would collapse them onto one connection — the second
session's WebSocket would silently take over the first's clicks. The process id
distinguishes them and dies with them.

The declared lease is short on purpose: a session's menu entry should leave the
bar shortly after the session does. The Hub sweeps a session whose lease lapses,
and the listen client's keepalive renews well inside that window, so a live
session never lapses and a dead one is gone within the minute.
"""

from __future__ import annotations

import os
from typing import Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.repo_root import RepoRoot

__all__ = ["SessionIdentity"]

# The project a session outside any repository owns its UI under — real and
# named, the headless counterpart of the repository directory name.
_HEADLESS_PROJECT = "lux-session"

# How long the Hub may go without hearing from this session before sweeping it.
# The listen client renews every 15s, so four beats may be lost before the menu
# entry goes — long enough to ride out a Hub restart, short enough that a killed
# session's entry does not linger.
_LEASE_TTL_SECONDS = 60.0


@final
class SessionIdentity:
    """One session server's declared identity, and the names derived from it."""

    _client: ClientIdentity
    _project: str
    __slots__ = ("_client", "_project")

    def __new__(cls, client: ClientIdentity, project: str) -> Self:
        self = super().__new__(cls)
        self._client = client
        self._project = project
        return self

    @classmethod
    def resolve(cls) -> Self:
        """Derive this process's identity from the repository it was started in."""
        repo = RepoRoot.of(_HEADLESS_PROJECT)
        return cls(
            ClientIdentity(
                kind="mcp-session",
                name=f"lux · {repo.name} · #{os.getpid():x}",
                repo=repo.declared_path,
                lease_ttl=_LEASE_TTL_SECONDS,
            ),
            repo.name,
        )

    @property
    def client(self) -> ClientIdentity:
        """The identity both Hub legs declare, and the menu labels this session."""
        return self._client

    @property
    def project(self) -> str:
        """The repository's directory name; this session's scenes are named for it."""
        return self._project

    @property
    def mcp_session_key(self) -> str:
        """The ``?session_key=`` this process's proxied MCP traffic claims.

        Deliberately *not* the connection id the identity derives: the agent's
        tool surface and the session's click-servicing leg are two connections
        with two jobs. Keeping them apart means the agent's scenes, subscriptions,
        and inbox are scoped to its own session while the service leg owns the
        menu callback, and the MCP session's idle reaping cannot take the menu
        entry with it. Stable for the life of the process, so every request in the
        session lands on one Hub connection rather than a fresh one per call.
        """
        return f"mcp-{self._client.name}"
