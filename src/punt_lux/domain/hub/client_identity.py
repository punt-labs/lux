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

# A cadence a session originator declared. One outside the bounds is rejected
# rather than clamped, so a caller learns its declaration was unusable instead of
# getting a length it did not ask for — stated declaratively, like ``_Label``, so
# the bound it violated names itself in the error.
_LeaseTtl = Annotated[
    float, Field(ge=_LEASE_TTL_FLOOR_SECONDS, le=_LEASE_TTL_CAP_SECONDS)
]


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
    # which keeps luxd's built-ins permanent. A present value is bounded.
    lease_ttl: _LeaseTtl | None = None

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
    def menu_label(self) -> str:
        """The name a human calls this client where a menu has to name it.

        A person names a client after the place it works: *the lux session*,
        *the quarry session*. So a client that declared a repository is called
        by that repository's directory, and one that declared none — a headless
        command, a machine-wide daemon like voxd — is called what it calls
        itself. One rule for every kind; the roster settles a collision between
        two clients that read the same way.

        This is deliberately not the declared ``name``: an applet's name carries
        the process id that keeps two sessions on the same repository from
        collapsing onto one connection, which is a distinctness token and not
        something to read aloud.
        """
        return self._repo_name or self.name

    @property
    def _repo_name(self) -> str:
        """The directory the declared repository ends in, blank when it ends in none.

        A path can be absolute and still name no directory — ``/``, and the
        ``/.`` and ``//`` that resolve to it. Such a repository contributes no
        name, as an absent one does not, so both fall back to the declared
        ``name``: stripped and non-empty on every accepted identity, which is
        what makes the label total. A root cwd is labelled, never refused.
        """
        return PurePath(self.repo).name.strip() if self.repo is not None else ""
