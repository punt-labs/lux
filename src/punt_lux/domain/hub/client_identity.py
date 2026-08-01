"""The identity a Hub client declares — what a connection attributes its UI to.

A client of Lux carries a *connection*, not an identity, until it declares one.
:class:`ClientIdentity` is that declaration: what kind of client it is, the name
the Hub shows for it, the repository it works in, and — for an agent — its
persona handle. Under the same-user-localhost trust model the Hub records the
declaration and verifies nothing; identity here is for attribution, not access
control.

The identity is metadata bound to a connection, never a replacement for it. The
wire ``ConnectionId`` stays the key that scopes a session's subscriptions, inbox,
and cleanup; :class:`~punt_lux.domain.hub.client_session.ClientSession` pairs that
connection's connect time with the identity it later declares.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

__all__ = ["ClientIdentity", "ClientKind"]

# The four kinds of client that reach the Hub. ``mcp-session`` is a Claude Code
# agent's live MCP connection, ``cli`` a ``lux`` command invocation, ``applet`` a
# session-bound program that owns menu entries and services their clicks, and
# ``app`` luxd itself declaring the built-in capabilities it owns.
ClientKind = Literal["mcp-session", "cli", "applet", "app"]

# A real, displayable label: whitespace is stripped and the result must be
# non-empty, so a blank or whitespace-only name is rejected declaratively rather
# than by a hand-written validator.
_Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# The bounds a declared lease TTL must fall within, in seconds. The floor keeps a
# session alive across its own contact round-trip — a lease shorter than a few
# seconds could sweep a client between two of its own beats — and the cap keeps a
# declared lease from defeating the sweep: a client claiming hours is
# indistinguishable from a leak, and an hour covers any real polling cadence (a
# cron client's twenty minutes sits well inside it). luxd's own built-ins declare
# no TTL and fall to the permanent ``app`` default, so the cap never binds them.
_LEASE_TTL_FLOOR_SECONDS = 5.0
_LEASE_TTL_CAP_SECONDS = 3600.0


class ClientIdentity(BaseModel):
    """What a client declares itself to be — the owner the Hub attributes UI to.

    ``kind`` is the discriminator; ``name`` is the human-readable label
    introspection prints. ``repo`` and ``agent`` are genuine absences, not
    give-ups: a headless CLI and the app own no repository, and only an agent
    carries a persona handle. Each is validated when present and left ``None``
    when the caller legitimately has neither.

    ``lease_ttl`` lets a session originator set how long it may idle between
    contacts — a cron client declares its cadence's length, a live daemon a short
    one so its menu entries leave when it dies. Absent is the documented default:
    the session falls to its kind's length, which is how luxd's built-ins stay
    permanent without declaring anything.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ClientKind
    name: _Label  # a real, stripped, non-empty attribution label
    repo: str | None = None  # absent for a headless CLI and the app; genuine
    # A non-blank handle when present; absent unless the caller is an agent.
    agent: str | None = Field(default=None, min_length=1)
    # Absent is not a give-up: it is the documented "use my kind's default" state,
    # which keeps luxd's built-ins permanent. A present value is bounded below.
    lease_ttl: float | None = None

    @field_validator("lease_ttl")
    @classmethod
    def _bound_lease_ttl(cls, value: float | None) -> float | None:
        """Accept an absent TTL, or a present one within the bounds; reject outside.

        Absence means the kind default. A present TTL is rejected at the boundary
        when it falls outside ``[floor, cap]`` rather than silently clamped, so a
        caller learns its cadence declaration was unusable instead of getting a
        length it did not ask for.
        """
        if value is not None and not (
            _LEASE_TTL_FLOOR_SECONDS <= value <= _LEASE_TTL_CAP_SECONDS
        ):
            msg = (
                f"lease_ttl must be between {_LEASE_TTL_FLOOR_SECONDS}s and "
                f"{_LEASE_TTL_CAP_SECONDS}s when declared; got {value}"
            )
            raise ValueError(msg)
        return value

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
