"""The identity a Hub client declares, and the session record that holds it.

A client of Lux carries a *connection*, not an identity, until it declares one.
:class:`ClientIdentity` is that declaration: what kind of client it is, the name
the Hub shows for it, the repository it works in, and — for an agent — its
persona handle. Under the same-user-localhost trust model the Hub records the
declaration and verifies nothing; identity here is for attribution, not access
control.

The identity is metadata bound to a connection, never a replacement for it. The
wire ``ConnectionId`` stays the key that scopes a session's subscriptions, inbox,
and cleanup; :class:`ClientSession` pairs that connection's connect time with the
identity it later declares, so the one Hub session registry answers both "how old
is this session?" and "who is it?" from a single record.

These types live in the domain layer because a client's identity is
Hub-authoritative state; the operations layer imports them, keeping the one
dependency arrow pointing operations → domain (PY-IC-9).
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Literal, Self, final

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["ClientIdentity", "ClientKind", "ClientSession"]

# The three front doors a client reaches the Hub through. ``mcp-session`` is a
# Claude Code agent's live MCP connection, ``cli`` a ``lux`` command invocation,
# and ``app`` luxd itself declaring the built-in capabilities it owns.
ClientKind = Literal["mcp-session", "cli", "app"]


class ClientIdentity(BaseModel):
    """What a client declares itself to be — the owner the Hub attributes UI to.

    ``kind`` is the discriminator; ``name`` is the human-readable label
    introspection prints. ``repo`` and ``agent`` are genuine absences, not
    give-ups: a headless CLI and the app own no repository, and only an agent
    carries a persona handle. Both are validated when present and left ``None``
    when the caller legitimately has neither.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ClientKind
    name: str = Field(min_length=1)  # a name-less client is not a real identity
    repo: str | None = None  # absent for a headless CLI and the app; genuine
    agent: str | None = None  # absent unless the caller is an agent with a handle

    @field_validator("repo")
    @classmethod
    def _validate_repo(cls, value: str | None) -> str | None:
        """Accept an absent repo or an absolute path; reject a relative one.

        The Hub records what a client declares, but a repository owner is an
        absolute path by definition (``one-code-path.md``), so a relative or
        blank string is a malformed declaration, not a headless client.
        """
        if value is None:
            return None
        if not value or not PurePath(value).is_absolute():
            msg = f"repo must be an absolute path when present; got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("agent")
    @classmethod
    def _validate_agent(cls, value: str | None) -> str | None:
        """Accept an absent agent or a non-blank handle; reject a blank one."""
        if value is None:
            return None
        if not value:
            msg = "agent must be a non-empty handle when present"
            raise ValueError(msg)
        return value

    @property
    def has_repo(self) -> bool:
        """Whether this client declared a repository to own its UI under."""
        return self.repo is not None


@final
class ClientSession:
    """One Hub session: when it connected and the identity it has declared.

    The registry keys these by ``ConnectionId``. A session exists from the moment
    a connection binds — with no identity yet — and gains one when the client
    calls ``identify``; :meth:`with_identity` returns the same connect time
    carrying the new declaration, so identifying never resets a session's age.
    """

    _connected_at: float
    _identity: ClientIdentity | None
    __slots__ = ("_connected_at", "_identity")

    def __new__(
        cls, connected_at: float, identity: ClientIdentity | None = None
    ) -> Self:
        self = super().__new__(cls)
        self._connected_at = connected_at
        self._identity = identity
        return self

    @property
    def connected_at(self) -> float:
        """The ``time.monotonic`` reading at which the session first registered."""
        return self._connected_at

    @property
    def identity(self) -> ClientIdentity | None:
        """The declared identity, or ``None`` while the session is unidentified."""
        return self._identity

    @property
    def declared_repo(self) -> str | None:
        """The repository this session declared, or ``None`` if it declared none.

        ``None`` for an unidentified session, a headless CLI, or the app — the
        value the registry's repository projection filters out.
        """
        return self._identity.repo if self._identity is not None else None

    def age(self, now: float) -> float:
        """Seconds since the session connected, clamped so it never goes negative."""
        return max(0.0, now - self._connected_at)

    def with_identity(self, identity: ClientIdentity) -> ClientSession:
        """Return this session carrying ``identity``, keeping its connect time."""
        return ClientSession(self._connected_at, identity)
