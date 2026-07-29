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
identity it later declares and the lease that keeps it live, so the one Hub
session registry answers "how old", "who", and "still live?" from one record.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Annotated, Literal, Self, final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from punt_lux.domain.hub.session_lease import SessionLease

__all__ = ["ClientIdentity", "ClientKind", "ClientSession"]

# The three front doors a client reaches the Hub through. ``mcp-session`` is a
# Claude Code agent's live MCP connection, ``cli`` a ``lux`` command invocation,
# and ``app`` luxd itself declaring the built-in capabilities it owns.
ClientKind = Literal["mcp-session", "cli", "app"]

# A real, displayable label: whitespace is stripped and the result must be
# non-empty, so a blank or whitespace-only name is rejected declaratively rather
# than by a hand-written validator.
_Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ClientIdentity(BaseModel):
    """What a client declares itself to be — the owner the Hub attributes UI to.

    ``kind`` is the discriminator; ``name`` is the human-readable label
    introspection prints. ``repo`` and ``agent`` are genuine absences, not
    give-ups: a headless CLI and the app own no repository, and only an agent
    carries a persona handle. Each is validated when present and left ``None``
    when the caller legitimately has neither.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ClientKind
    name: _Label  # a real, stripped, non-empty attribution label
    repo: str | None = None  # absent for a headless CLI and the app; genuine
    # A non-blank handle when present; absent unless the caller is an agent.
    agent: str | None = Field(default=None, min_length=1)

    @field_validator("repo")
    @classmethod
    def _validate_repo(cls, value: str | None) -> str | None:
        """Accept an absent repo or an absolute path; reject a relative or blank one.

        A repository owner is an absolute path by definition (``one-code-path.md``),
        so a relative or blank string — ``PurePath("").is_absolute()`` is false — is
        a malformed declaration, not a headless client.
        """
        if value is not None and not PurePath(value).is_absolute():
            msg = f"repo must be an absolute path when present; got {value!r}"
            raise ValueError(msg)
        return value

    @property
    def has_repo(self) -> bool:
        """Whether this client declared a repository to own its UI under."""
        return self.repo is not None


@final
class ClientSession:
    """One Hub session: its connect time, declared identity, and renewal lease.

    The registry keys these by ``ConnectionId``. A session exists from the moment a
    connection binds — with no identity yet and an unidentified-grace lease — and
    gains an identity when the client calls ``identify``. Any authenticated contact
    renews the lease; declaring an identity also resets the lease length to the one
    its kind declares. Identifying never resets a session's connect time, so age
    keeps climbing across a re-identify.
    """

    _connected_at: float
    _identity: ClientIdentity | None
    _lease: SessionLease
    __slots__ = ("_connected_at", "_identity", "_lease")

    def __new__(
        cls,
        connected_at: float,
        identity: ClientIdentity | None = None,
        lease: SessionLease | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._connected_at = connected_at
        self._identity = identity
        self._lease = (
            lease if lease is not None else SessionLease.unidentified(connected_at)
        )
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

    def is_live(self, now: float) -> bool:
        """Whether the session's lease has not lapsed as of ``now``."""
        return self._lease.is_live(now)

    def renewed(self, now: float) -> ClientSession:
        """Return this session with its lease renewed at ``now``; any contact renews."""
        lease = self._lease.renewed(now)
        return ClientSession(self._connected_at, self._identity, lease)

    def with_identity(self, identity: ClientIdentity) -> ClientSession:
        """Return this session carrying ``identity`` and its kind's lease length.

        The connect time is kept, and the lease is reset to the length ``identity``'s
        kind declares while holding the current renewal instant — declaring who you
        are both attributes the session and sets how long it may idle.
        """
        lease = SessionLease.for_kind(identity.kind, self._lease.renewed_at)
        return ClientSession(self._connected_at, identity, lease)
