"""The ``X-Lux-Client-*`` header contract, owned once for both wire directions.

A CLI or REST caller declares who it is in request headers; the Hub reads that
declaration back. Both ends must agree on the header names and the shape they
carry, so one class owns them: :meth:`ClientHeaders.to_wire` renders an identity
into the request headers, and :meth:`ClientHeaders.declaration_from` reads them
back into the declaration the ``identify`` operation validates — defining the
contract once keeps the client's write and the server's read from drifting apart.

This class owns the header names and which fields are present; how one value
survives the wire belongs to :class:`~punt_lux.header_value.HeaderValue`.

The challenge header is the response side of the same contract: the Hub stamps it
on a write that arrived without an identity — the HTTP analogue of a 401 challenge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final

from punt_lux.header_value import HeaderValue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["ClientHeaders"]

# What a caller that named itself but not its kind is taken to be — a `lux`
# command is the client that reaches the Hub without declaring what it is.
_DEFAULT_KIND = "cli"


@final
class ClientHeaders:
    """The client-identity header names and the two directions they cross in."""

    KIND: ClassVar[str] = "X-Lux-Client-Kind"
    NAME: ClassVar[str] = "X-Lux-Client-Name"
    REPO: ClassVar[str] = "X-Lux-Client-Repo"
    AGENT: ClassVar[str] = "X-Lux-Client-Agent"
    # The declared lease TTL, in seconds — a session's chosen cadence length. Absent
    # means the kind default (see ClientIdentity.lease_ttl).
    LEASE_TTL: ClassVar[str] = "X-Lux-Client-Lease-Ttl"
    # The response header a Hub stamps on an identity-less write — the challenge.
    CHALLENGE: ClassVar[str] = "X-Lux-Identification-Required"
    # Which identity field each header carries, read once from this one table so
    # the two directions cannot come to disagree about the set.
    FIELDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("kind", KIND),
        ("name", NAME),
        ("repo", REPO),
        ("agent", AGENT),
        ("lease_ttl", LEASE_TTL),
    )
    __slots__ = ()

    @classmethod
    def to_wire(cls, identity: ClientIdentity) -> dict[str, str]:
        """Render ``identity`` into the request headers a client sends.

        ``kind`` and ``name`` are always present; ``repo``, ``agent``, and
        ``lease_ttl`` are genuine absences (a headless CLI owns no repository, only
        an agent carries a persona, and an undeclared TTL means the kind default),
        and an absent field is omitted rather than sent blank. That is the one rule
        this method applies: every field is rendered, and the blank ones are dropped
        — a blank header equals no header on the read side.
        """
        return {header: value for header, value in cls._rendered(identity) if value}

    @staticmethod
    def _rendered(identity: ClientIdentity) -> tuple[tuple[str, str], ...]:
        """Each header and the text this identity gives it; ``""`` means absent.

        Values cross as the ASCII :class:`~punt_lux.header_value.HeaderValue`
        renders, so a non-ASCII name or repository path reaches the Hub as the same
        bytes on every transport. The TTL is a number, not a declared label, so it
        is formatted rather than encoded.
        """
        return (
            (ClientHeaders.KIND, identity.kind),
            (ClientHeaders.NAME, HeaderValue.sent(identity.name)),
            (ClientHeaders.REPO, HeaderValue.sent(identity.repo)),
            (ClientHeaders.AGENT, HeaderValue.sent(identity.agent)),
            (
                ClientHeaders.LEASE_TTL,
                "" if identity.lease_ttl is None else str(identity.lease_ttl),
            ),
        )

    @classmethod
    def declaration_from(cls, headers: Mapping[str, str]) -> dict[str, object] | None:
        """Read the identity headers into a declaration, or ``None`` if unnamed.

        A request is identified when it names itself, so a declaration with no name
        is no declaration — ``None`` is the documented contract for an unidentified
        caller, not a give-up on the type. ``kind`` falls to ``cli`` when the caller
        declared none. A declared ``lease_ttl`` rides as a string the identity model
        coerces and bounds-checks, so a non-numeric or out-of-range value is a named
        rejection, not a crash.
        """
        declared = cls._declared(headers)
        return None if "name" not in declared else {"kind": _DEFAULT_KIND} | declared

    @classmethod
    def _declared(cls, headers: Mapping[str, str]) -> dict[str, object]:
        """The fields these headers actually declare, blank ones dropped.

        The mirror of :meth:`to_wire`'s rule, and the same one absence spelling: a
        missing header and a blank one both mean the caller declared no such field,
        so neither reaches ``identify`` (which rejects a blank repo or agent).
        Each value comes back through :class:`~punt_lux.header_value.HeaderValue`,
        which undoes what :meth:`to_wire` wrote and recovers a raw value the
        transport garbled — so both of a session's legs read one identity whichever
        way their client encoded it.
        """
        return {
            field: value
            for field, header in cls.FIELDS
            if (value := HeaderValue.declared(headers.get(header, "")))
        }
