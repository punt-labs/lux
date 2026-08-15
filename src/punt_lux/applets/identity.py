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
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.repo_root import RepoRoot

__all__ = ["AppletIdentity"]

# What an applet outside any repository calls itself.
_HEADLESS_NAME = "lux-session"

# Sweep-cadence bounds: longer than several 15s keepalives, short enough that
# a killed session's menu entry leaves the bar within the minute.
_LEASE_TTL_SECONDS = 60.0

# The ``name`` format ``for_session`` writes and ``session_pid_of`` reads back:
# ``lux · <repo> · #<pid> · <program>``. A format change lands both halves at
# once; the round-trip test in ``tests/applets/test_identity.py`` fails loud
# if either half moves alone.
_NAME_SEPARATOR = " · "
_PID_PART_INDEX = 2
_PID_PART_PREFIX = "#"
_NAME_PART_COUNT = 4


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
        parts = ("lux", repo.name, f"{_PID_PART_PREFIX}{session_pid:x}", program)
        return cls(
            ClientIdentity(
                kind="applet",
                name=_NAME_SEPARATOR.join(parts),
                repo=repo.declared_path,
                lease_ttl=_LEASE_TTL_SECONDS,
            )
        )

    @classmethod
    def session_pid_of(cls, client: ClientIdentity) -> int | None:
        """Return the applet's session pid, or ``None`` for a non-applet.

        Only an applet is named ``lux · <repo> · #<pid> · <program>``, so a
        non-applet returns ``None`` — the documented absence the menu-grouping
        composer skips on. An applet whose name does not parse raises
        :class:`ValueError` rather than silently mis-group.
        """
        return cls._parse_pid(client.name) if client.kind == "applet" else None

    @classmethod
    def _parse_pid(cls, name: str) -> int:
        """Return the pid the four-part applet name embeds, or reject the name."""
        parts = name.split(_NAME_SEPARATOR)
        pid_part = parts[_PID_PART_INDEX] if len(parts) == _NAME_PART_COUNT else ""
        try:
            return int(pid_part.removeprefix(_PID_PART_PREFIX), 16)
        except ValueError as exc:
            msg = f"malformed applet name: {name!r}"
            raise ValueError(msg) from exc

    @property
    def client(self) -> ClientIdentity:
        """The identity both Hub legs declare."""
        return self._client
