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
