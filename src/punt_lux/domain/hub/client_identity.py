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
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.applet_name_format import APPLET_NAME_RE

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId

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

    @field_validator("name", "repo", "agent")
    @classmethod
    def _reject_nul(cls, value: str | None) -> str | None:
        """Reject a NUL in any field, wherever the declaration came from.

        :func:`~punt_lux.connection_identity.connection_for` joins these fields
        on a NUL to derive a connection id; a field that carries one breaks that
        join's distinctness guarantee. ``name`` is the field most exposed to
        this, since it can carry caller-supplied content such as an applet's
        program, but the guarantee holds only if every source is caught here,
        not just the ones an author remembered to check upstream.
        """
        if value is not None and "\x00" in value:
            msg = (
                "identity fields must not contain NUL (breaks the "
                "connection_for concatenation invariant)"
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_applet_shape(self) -> Self:
        """An applet's name must be the four-part shape the grouping composer parses.

        The menu-grouping composer reads the session pid off an applet's
        ``name`` to fold sibling applets into one submenu (DES-067). A name
        that cannot yield a pid is rejected at construction rather than
        silently degrading to per-connection grouping — including the case
        where a repo directory contains the format separator and the
        composed name comes out malformed. Applets are legitimately headless
        (``repo=None``) — see :meth:`AppletIdentity.for_session` — so the
        repo alone is not enough to reject on.
        """
        if self.kind == "applet" and APPLET_NAME_RE.match(self.name) is None:
            msg = (
                "an applet name must match "
                "'lux · <repo> · #<pid> · <program>'; got "
                f"{self.name!r}"
            )
            raise ValueError(msg)
        return self

    @property
    def connection_id(self) -> ConnectionId:
        """This identity's stable connection id (DES-086), derived deterministically."""
        return connection_for(self.model_dump())

    @property
    def menu_label(self) -> str:
        """The name a human calls this client where a menu has to name it.

        A repo-declared client is named by its repository's directory; a
        headless one (a command, voxd) is called what it calls itself. Not the
        declared ``name`` -- an applet's name carries a distinctness pid.
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
