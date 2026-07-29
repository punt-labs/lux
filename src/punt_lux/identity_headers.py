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

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["ClientHeaders"]


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
        """
        headers = {cls.KIND: identity.kind, cls.NAME: identity.name}
        if identity.repo is not None:
            headers[cls.REPO] = identity.repo
        if identity.agent is not None:
            headers[cls.AGENT] = identity.agent
        if identity.lease_ttl is not None:
            headers[cls.LEASE_TTL] = str(identity.lease_ttl)
        return headers

    @classmethod
    def declaration_from(cls, headers: Mapping[str, str]) -> dict[str, object] | None:
        """Read the identity headers into a declaration, or ``None`` if unnamed.

        A request is identified when it names itself; ``kind`` defaults to ``cli``.
        A blank or whitespace-only header equals no header — dropped, not passed to
        ``identify`` (which rejects a blank repo/agent). ``None`` is the documented
        contract for an unidentified caller, not a give-up on the type. A declared
        ``lease_ttl`` rides as a string the identity model coerces and bounds-checks,
        so a non-numeric or out-of-range value is a named rejection, not a crash.
        """
        name = headers.get(cls.NAME, "").strip()
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
            value = headers.get(header, "").strip()
            if value:
                declaration[field] = value
        return declaration
