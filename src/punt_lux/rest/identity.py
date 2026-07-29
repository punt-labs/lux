"""RestCaller — resolve each REST request's identity and owning scope.

A REST request declares who it is in ``X-Lux-Client-*`` headers; this resolver
turns that declaration into the :class:`~punt_lux.operations.scope.Scope` the
request's writes own. An identified request records its identity against a
connection derived deterministically from that identity — so the same caller
owns the same scenes across requests — while an unidentified request gets a
distinct per-request connection (two anonymous callers never share ownership)
and carries the ``identification_required`` challenge on its response.

There is no reserved shared connection: every caller carries a real, named
identity, or an anonymous one unique to the request.
"""

from __future__ import annotations

import uuid
from hashlib import blake2s
from typing import TYPE_CHECKING, Final, Self, cast, final

from starlette.requests import Request
from starlette.responses import Response

from punt_lux.domain.ids import ConnectionId
from punt_lux.operations.scope import Scope

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["CHALLENGE_HEADER", "RestCaller", "resolve_scope"]


def resolve_scope(request: Request, response: Response) -> Scope:
    """FastAPI dependency: the owning scope for a write route, from its identity.

    The mounted :class:`RestSurface` stores its :class:`RestCaller` on ``app.state``,
    so every write route shares one resolver as a single ``scope`` parameter rather
    than threading the resolver through each route and taking the raw request.
    """
    caller = cast("RestCaller", request.app.state.rest_caller)
    return caller.resolve(request, response)


# The response header an identity-less write carries — the HTTP analogue of a
# 401/403 challenge. A caller learns from it that owning UI needs an identity.
CHALLENGE_HEADER: Final = "X-Lux-Identification-Required"

_KIND = "X-Lux-Client-Kind"
_NAME = "X-Lux-Client-Name"
_REPO = "X-Lux-Client-Repo"
_AGENT = "X-Lux-Client-Agent"
_CHALLENGE_REASON: Final = "declare an identity to own the scenes this request creates"


@final
class RestCaller:
    """Resolve one REST request's owning scope from its ``X-Lux-Client-*`` headers."""

    _ops: Operations
    _errors: HttpErrorMap
    __slots__ = ("_errors", "_ops")

    def __new__(cls, ops: Operations, errors: HttpErrorMap) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._errors = errors
        return self

    def resolve(self, request: Request, response: Response) -> Scope:
        """Return the scope this request's writes own, challenging an anonymous one.

        A named request records its declared identity against a stable, derived
        connection and returns that scope. A nameless request is given a distinct
        per-request connection and its response carries the challenge header — the
        write still proceeds, but the caller is told it must identify to own UI.
        """
        declaration = self._declaration(request)
        if declaration is None:
            response.headers[CHALLENGE_HEADER] = _CHALLENGE_REASON
            return Scope(ConnectionId(f"anon-{uuid.uuid4().hex[:12]}"))
        scope = Scope(self._connection_for(declaration))
        self._errors.respond(self._ops.identify(declaration, scope=scope))
        return scope

    @staticmethod
    def _declaration(request: Request) -> dict[str, object] | None:
        """Read the identity headers into a declaration, or ``None`` if unnamed.

        A request is identified when it names itself; ``kind`` defaults to ``cli``.
        A blank or whitespace-only header equals no header — dropped, not passed to
        ``identify`` (which rejects a blank repo/agent); it validates what remains.
        """
        name = request.headers.get(_NAME, "").strip()
        if not name:
            return None
        declaration: dict[str, object] = {
            "kind": request.headers.get(_KIND, "cli"),
            "name": name,
        }
        for field, header in (("repo", _REPO), ("agent", _AGENT)):
            value = request.headers.get(header, "").strip()
            if value:
                declaration[field] = value
        return declaration

    @staticmethod
    def _connection_for(declaration: dict[str, object]) -> ConnectionId:
        """Derive a stable connection id from the declared identity.

        Deterministic in the identity fields, so a caller that re-declares the same
        identity owns the same scenes across requests; distinct identities never
        collide. Not a credential — attribution under the same-user trust model.
        """
        parts = (
            declaration.get(field, "") for field in ("kind", "name", "repo", "agent")
        )
        seed = "\x00".join(str(part) for part in parts)
        return ConnectionId(blake2s(seed.encode(), digest_size=8).hexdigest())
