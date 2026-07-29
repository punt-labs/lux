"""The ``X-Lux-Client-*`` header contract, owned once for both wire directions.

A CLI or REST caller declares who it is in request headers; the Hub reads that
declaration back. Both ends must agree on the header names and the shape they
carry, so one class owns them: :meth:`ClientHeaders.to_wire` renders an identity
into the request headers the client sends, and :meth:`ClientHeaders.declaration_from`
reads those same headers into the declaration the ``identify`` operation validates.
Defining the contract in one place keeps the client's write and the server's read
from drifting apart.

The challenge header is the response side of the same contract: the Hub stamps it
on a write that arrived without an identity, so the caller learns owning UI needs
one — the HTTP analogue of a 401/403 challenge.
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
    # The response header a Hub stamps on an identity-less write — the challenge.
    CHALLENGE: ClassVar[str] = "X-Lux-Identification-Required"
    __slots__ = ()

    @classmethod
    def to_wire(cls, identity: ClientIdentity) -> dict[str, str]:
        """Render ``identity`` into the request headers a client sends.

        ``kind`` and ``name`` are always present; ``repo`` and ``agent`` are
        genuine absences (a headless CLI owns no repository, only an agent carries
        a persona), so an absent one is omitted rather than sent blank — a blank
        header equals no header on the read side.
        """
        headers = {cls.KIND: identity.kind, cls.NAME: identity.name}
        if identity.repo is not None:
            headers[cls.REPO] = identity.repo
        if identity.agent is not None:
            headers[cls.AGENT] = identity.agent
        return headers

    @classmethod
    def declaration_from(cls, headers: Mapping[str, str]) -> dict[str, object] | None:
        """Read the identity headers into a declaration, or ``None`` if unnamed.

        A request is identified when it names itself; ``kind`` defaults to ``cli``.
        A blank or whitespace-only header equals no header — dropped, not passed to
        ``identify`` (which rejects a blank repo/agent). ``None`` is the documented
        contract for an unidentified caller, not a give-up on the type.
        """
        name = headers.get(cls.NAME, "").strip()
        if not name:
            return None
        declaration: dict[str, object] = {
            "kind": headers.get(cls.KIND, "cli"),
            "name": name,
        }
        for field, header in (("repo", cls.REPO), ("agent", cls.AGENT)):
            value = headers.get(header, "").strip()
            if value:
                declaration[field] = value
        return declaration
