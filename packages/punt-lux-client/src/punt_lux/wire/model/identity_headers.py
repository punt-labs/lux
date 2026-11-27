"""The ``X-Lux-Client-*`` header contract, owned once for both wire directions.

A CLI or REST caller declares who it is in request headers; the Hub reads that
declaration back. Both ends must agree on the header names and the shape they
carry, so one class owns them: :meth:`ClientHeaders.to_wire` renders an identity
into the request headers, and :meth:`ClientHeaders.declaration_from` reads them
back into the declaration the ``identify`` operation validates — defining the
contract once keeps the client's write and the server's read from drifting apart.

This class owns the header names and which fields are present; how one value
survives the wire belongs to :class:`~punt_lux.wire.model.header_value.HeaderValue`.

The challenge header is the response side of the same contract: the Hub stamps it
on a write that arrived without an identity — the HTTP analogue of a 401 challenge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final

from pydantic import ValidationError

from punt_lux.kernel.client_host import ClientHost
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.model.identity_header_field import IdentityHeaderField

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.kernel.peer_connection import HeaderedConnection

__all__ = ["ClientHeaders"]

# What a caller that named itself but not its kind is taken to be — a `lux`
# command is the client that reaches the Hub without declaring what it is.
_DEFAULT_KIND = "cli"


@final
class ClientHeaders:
    """The client-identity header names and the two directions they cross in."""

    # The response header a Hub stamps on an identity-less write — the challenge.
    CHALLENGE: ClassVar[str] = "X-Lux-Identification-Required"
    # The identity fields that cross the wire, declared once so the two directions
    # cannot come to disagree about the set. ``lease_ttl`` absent means the kind
    # default (see ClientIdentity.lease_ttl).
    FIELDS: ClassVar[tuple[IdentityHeaderField, ...]] = (
        IdentityHeaderField("kind", "X-Lux-Client-Kind", is_encoded=False),
        IdentityHeaderField("name", "X-Lux-Client-Name"),
        IdentityHeaderField("host", "X-Lux-Client-Host"),
        IdentityHeaderField("repo", "X-Lux-Client-Repo"),
        IdentityHeaderField("agent", "X-Lux-Client-Agent"),
        IdentityHeaderField("lease_ttl", "X-Lux-Client-Lease-Ttl", is_encoded=False),
    )
    __slots__ = ()

    @classmethod
    def to_wire(cls, identity: ClientIdentity) -> dict[str, str]:
        """Render ``identity`` into the request headers a client sends.

        ``kind``, ``name`` and ``host`` are always present; ``repo``, ``agent``, and
        ``lease_ttl`` are genuine absences (a headless CLI owns no repository, only
        an agent carries a persona, and an undeclared TTL means the kind default),
        and an absent field is omitted rather than sent blank — a blank header
        equals no header on the read side. Free text crosses as the ASCII
        :class:`~punt_lux.wire.model.header_value.HeaderValue` renders, so a
        non-ASCII name or path reaches the Hub as the same bytes on every transport.
        """
        return {
            field.header: text
            for field in cls.FIELDS
            if (text := field.render(identity))
        }

    @classmethod
    def declaration_from(
        cls, connection: HeaderedConnection
    ) -> dict[str, object] | None:
        """Read the connection's identity headers into a declaration, or ``None``.

        A request is identified when it names itself, so a declaration with no name
        is no declaration — ``None`` is the documented contract for an unidentified
        caller, not a give-up on the type. ``kind`` falls to ``cli`` when the caller
        declared none. A caller that declared no ``host`` is taken to run where its
        socket came from, never where the Hub runs: a client reaching
        the Hub through a tunnel must not be recorded as the Hub's own machine. An
        unobserved caller (in-process) declares none and keeps the identity default.

        A declared ``lease_ttl`` rides as a string the identity model
        coerces and bounds-checks, so a non-numeric or out-of-range value is a named
        rejection, not a crash.
        """
        declared = cls._declared(connection.headers)
        if "name" not in declared:
            return None
        observed = ClientHost.of_connection(connection)
        peer = {"host": observed.address} if observed.observed else {}
        return {"kind": _DEFAULT_KIND} | peer | declared

    @classmethod
    def identity_from(cls, connection: HeaderedConnection) -> ClientIdentity | None:
        """Parse ``connection``'s headers into an identity, or ``None`` for no caller.

        ``None`` covers both a genuinely unnamed request and a named-but-malformed
        one (a garbled ``lease_ttl``, an out-of-range value) — a read route that
        calls this is choosing not to challenge on identity, so a header the
        caller botched degrades to the same "no identity declared" outcome a
        caller who sent nothing at all gets, rather than a 401 a read never asks
        for. A write route that must reject a malformed declaration outright
        uses :meth:`declaration_from` plus the ``identify`` operation instead,
        which returns the named validation error.
        """
        declared = cls.declaration_from(connection)
        if declared is None:
            return None
        try:
            return ClientIdentity.model_validate(declared)
        except ValidationError:
            return None

    @classmethod
    def _declared(cls, headers: Mapping[str, str]) -> dict[str, object]:
        """Return only identity headers with nonblank values.

        The mirror of :meth:`to_wire`'s rule, and the same one absence spelling: a
        missing header and a blank one both mean the caller declared no such field,
        so neither reaches ``identify`` (which rejects a blank repo or agent).
        Each value comes back through
        :class:`~punt_lux.wire.model.header_value.HeaderValue`, which undoes what
        :meth:`to_wire` wrote and recovers a raw value the
        transport garbled — so both of a session's legs read one identity whichever
        way their client encoded it.
        """
        return {
            field.name: text for field in cls.FIELDS if (text := field.read(headers))
        }
