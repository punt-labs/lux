"""AppletIdentity — what one applet declares itself to be.

An applet owns two legs into the Hub: the WebSocket it holds open for its menu
clicks, and the REST calls it makes to push what those clicks produce. Both
must resolve to one Hub connection, so both declare this identity, and
:func:`~punt_lux.connection_identity.connection_for` derives the shared
connection id from its fields.

The name reads as one uniform shape — ``lux · <repository> · #<session> ·
<program>`` — with each part carrying a distinct guarantee. The session id
keeps two Claude Code sessions on one repository from collapsing onto one
connection (the second's WebSocket would silently take over the first's
clicks). The program name keeps two applets in one session from doing the
same. Empty, whitespace-only, and NUL-carrying programs are rejected.

The declared lease is short: the Hub sweeps a session whose lease lapses, and
the listen client renews well inside that window, so a live session never
lapses and a dead one is gone within the minute.

The name-format's writer sits here and its reader in
:mod:`~punt_lux.domain.hub.applet_name_format`, both driven by the same
module of constants and functions so a format change lands both halves.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub import applet_name_format
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.repo_root import RepoRoot

__all__ = ["AppletIdentity"]

# What an applet outside any repository calls itself.
_HEADLESS_NAME = "lux-session"

# Sweep-cadence bounds: longer than several 15s keepalives, short enough that
# a killed session's menu entry leaves the bar within the minute.
_LEASE_TTL_SECONDS = 60.0


@final
class AppletIdentity:
    """One applet's declared identity, and the menu label derived from it."""

    _client: ClientIdentity
    __slots__ = ("_client",)

    def __new__(cls, client: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._client = client
        return self

    @classmethod
    def for_session(cls, program: str, session_pid: int) -> Self:
        """Derive this applet's identity from its program, session, and repository."""
        if not (program := program.strip()):
            msg = "program must be a non-empty, non-whitespace label"
            raise ValueError(msg)
        if "\x00" in program:
            msg = "program must not contain a NUL character"
            raise ValueError(msg)
        repo = RepoRoot.of(_HEADLESS_NAME)
        return cls(
            ClientIdentity(
                kind="applet",
                name=applet_name_format.format_name(repo.name, session_pid, program),
                repo=repo.declared_path,
                lease_ttl=_LEASE_TTL_SECONDS,
            )
        )

    @classmethod
    def session_pid_of(cls, client: ClientIdentity) -> int | None:
        """Return the applet's session pid, or ``None`` for a non-applet."""
        return applet_name_format.session_pid_of(client)

    @property
    def client(self) -> ClientIdentity:
        """The identity both Hub legs declare."""
        return self._client
