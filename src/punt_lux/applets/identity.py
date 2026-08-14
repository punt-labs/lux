"""AppletIdentity — what one applet declares itself to be.

An applet owns two legs into the Hub: the WebSocket it holds open to receive its
menu clicks, and the REST calls it makes to push what those clicks produce. Both
must resolve to one Hub connection, so both declare this identity;
:func:`~punt_lux.connection_identity.connection_for` derives the shared
connection id from its fields.

The name is what a user reads in the menu bar, so it says four things in one
uniform shape — ``lux · <repository> · #<session> · <program>``: which tool the
entries belong to, which repository this session works in, which of possibly
several sessions on that repository it is, and which program within that
session declared it.

The session id is not cosmetic. Two Claude Code sessions open on the same
repository are two separate services with separate menu entries, and identities
that compared equal would collapse them onto one connection — the second
session's WebSocket would silently take over the first's clicks. The session's
process id distinguishes them, and it is the *session's* rather than the applet's
for the same reason the applet watches it: the entry belongs to the session. An
applet restarted against a live session comes back as the same identity and takes
its own entry over, which is what the succession rules are for.

The program name is not cosmetic either, and for the sibling reason: one
session can run more than one applet at once — ``lux-beads`` and a tool's own
applet both alive under the same Claude Code process — and without a program
token they derive the same identity from the same ``(repo, session_pid)`` pair.
Whichever registered its callback later would silently clobber the earlier one's
connection, the same collapse the session id already guards against one level
up. The caller names its own program; there is no default, because a shared
default would recreate the exact collision this field exists to prevent — which
is why an empty or all-whitespace program is rejected rather than silently
accepted as one. It is also rejected if it carries a NUL, the character
:func:`~punt_lux.connection_identity.connection_for` joins fields on: this
field is the one carrying caller-supplied content, so it is the one that must
keep that character out.

The declared lease is short on purpose: a session's menu entry should leave the
bar shortly after the session does. The Hub sweeps a session whose lease lapses,
and the listen client's keepalive renews well inside that window, so a live
session never lapses and a dead one is gone within the minute — even if the
applet's own exit went wrong.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.repo_root import RepoRoot

__all__ = ["AppletIdentity"]

# What an applet outside any repository calls itself — real and named, the
# headless counterpart of the repository directory name.
_HEADLESS_NAME = "lux-session"

# How long the Hub may go without hearing from this applet before sweeping it.
# The listen client renews every 15s, so four beats may be lost before the menu
# entry goes — long enough to ride out a Hub restart, short enough that a killed
# session's entry does not linger.
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
        if not program.strip():
            msg = (
                "program must be a non-empty, non-whitespace label; an empty "
                "program would recreate the collision this field exists to prevent"
            )
            raise ValueError(msg)
        if "\x00" in program:
            msg = "program must not contain a NUL character"
            raise ValueError(msg)
        repo = RepoRoot.of(_HEADLESS_NAME)
        return cls(
            ClientIdentity(
                kind="applet",
                name=f"lux · {repo.name} · #{session_pid:x} · {program}",
                repo=repo.declared_path,
                lease_ttl=_LEASE_TTL_SECONDS,
            )
        )

    @property
    def client(self) -> ClientIdentity:
        """The identity both Hub legs declare, and the menu label this applet."""
        return self._client
