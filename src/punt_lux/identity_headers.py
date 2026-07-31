"""The ``X-Lux-Client-*`` header contract, owned once for both wire directions.

A CLI or REST caller declares who it is in request headers; the Hub reads that
declaration back. Both ends must agree on the header names and the shape they
carry, so one class owns them: :meth:`ClientHeaders.to_wire` renders an identity
into the request headers, and :meth:`ClientHeaders.declaration_from` reads them
back into the declaration the ``identify`` operation validates — defining the
contract once keeps the client's write and the server's read from drifting apart.

The challenge header is the response side of the same contract: the Hub stamps it
on a write that arrived without an identity — the HTTP analogue of a 401 challenge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final
from urllib.parse import quote, unquote

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["ClientHeaders"]

# Header values cross as ASCII, so anything else is percent-encoded here and
# decoded on the read. The transports do not agree about the alternative: the
# WebSocket client sends UTF-8 bytes where the HTTP client sends latin-1, and a
# server decoding one as the other reads a different string — which resolves to a
# different connection id, splitting one session's two legs into two connections
# that cannot see each other's callbacks. A repository path with an accent in it
# is enough to trigger that, so the encoding is not optional.
#
# Every printable ASCII character except ``%`` is left alone, so the values
# callers have today cross the wire byte-for-byte as before; ``%`` itself is
# encoded so a value containing one still round-trips.
_WIRE_SAFE = " !\"#$&'()*+,-./:;<=>?@[\\]^_`{|}~"


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
    __slots__ = ()

    @classmethod
    def to_wire(cls, identity: ClientIdentity) -> dict[str, str]:
        """Render ``identity`` into the request headers a client sends.

        ``kind`` and ``name`` are always present; ``repo``, ``agent``, and
        ``lease_ttl`` are genuine absences (a headless CLI owns no repository, only
        an agent carries a persona, and an undeclared TTL means the kind default), so
        an absent one is omitted rather than sent blank — a blank header equals no
        header on the read side.

        Values are percent-encoded so a non-ASCII name or repository path crosses
        every transport as the same bytes; :meth:`declaration_from` reverses it.
        """
        headers = {cls.KIND: identity.kind, cls.NAME: cls._encode(identity.name)}
        if identity.repo is not None:
            headers[cls.REPO] = cls._encode(identity.repo)
        if identity.agent is not None:
            headers[cls.AGENT] = cls._encode(identity.agent)
        if identity.lease_ttl is not None:
            headers[cls.LEASE_TTL] = str(identity.lease_ttl)
        return headers

    @staticmethod
    def _encode(value: str) -> str:
        """Render a declared value as ASCII the wire carries unambiguously."""
        return quote(value, safe=_WIRE_SAFE)

    @staticmethod
    def _decode(value: str) -> str:
        """Read a wire value back; an ASCII value with no escape is unchanged."""
        return unquote(value)

    @classmethod
    def declaration_from(cls, headers: Mapping[str, str]) -> dict[str, object] | None:
        """Read the identity headers into a declaration, or ``None`` if unnamed.

        A request is identified when it names itself; ``kind`` defaults to ``cli``.
        A blank or whitespace-only header equals no header — dropped, not passed to
        ``identify`` (which rejects a blank repo/agent). ``None`` is the documented
        contract for an unidentified caller, not a give-up on the type. A declared
        ``lease_ttl`` rides as a string the identity model coerces and bounds-checks,
        so a non-numeric or out-of-range value is a named rejection, not a crash.

        Values are percent-decoded, the inverse of what :meth:`to_wire` wrote, so
        both of a session's legs read one identity out of their own transport's
        header encoding.
        """
        name = cls._decode(headers.get(cls.NAME, "")).strip()
        if not name:
            return None
        # A blank kind equals no kind — stripped and defaulted to cli, not sent on.
        kind = headers.get(cls.KIND, "").strip()
        declaration: dict[str, object] = {
            "kind": kind if kind else "cli",
            "name": name,
        }
        optional = (
            ("repo", cls.REPO),
            ("agent", cls.AGENT),
            ("lease_ttl", cls.LEASE_TTL),
        )
        for field, header in optional:
            value = cls._decode(headers.get(header, "")).strip()
            if value:
                declaration[field] = value
        return declaration
