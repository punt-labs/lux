"""RestCaller — resolve each REST request's identity and owning scope.

A REST request declares who it is in ``X-Lux-Client-*`` headers; this resolver
turns that declaration into the :class:`~punt_lux.operations.scope.Scope` the
request's writes own. An identified request records its identity against a
connection derived deterministically from that identity, so the same caller owns
the same scenes across requests. A request that carries no identity is refused
with the ``identification_required`` challenge — a write owns UI, and only a named
caller may — while reads take no scope and stay open to an unnamed caller.
"""

from __future__ import annotations

from hashlib import blake2s
from typing import TYPE_CHECKING, Final, Self, cast, final

from fastapi import HTTPException
from starlette.requests import Request

from punt_lux.domain.ids import ConnectionId
from punt_lux.identity_headers import ClientHeaders
from punt_lux.operations.scope import Scope

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["RestCaller", "resolve_scope"]


def resolve_scope(request: Request) -> Scope:
    """FastAPI dependency: the owning scope for a write route, from its identity.

    The mounted :class:`RestSurface` stores its :class:`RestCaller` on ``app.state``,
    so every write route shares one resolver as a single ``scope`` parameter rather
    than threading the resolver through each route and taking the raw request.
    """
    caller = cast("RestCaller", request.app.state.rest_caller)
    return caller.resolve(request)


_CHALLENGE_REASON: Final = "declare an identity to own the writes this request makes"


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

    def resolve(self, request: Request) -> Scope:
        """Return the scope this request's writes own, or reject an unidentified one.

        A named request records its declared identity against a stable, derived
        connection and returns that scope. A request that carries no identity is
        refused with the ``identification_required`` challenge (a 401 carrying the
        challenge header), so nothing anonymous owns a write — a scene or a menu item.
        """
        declaration = self._declaration(request)
        if declaration is None:
            raise HTTPException(
                status_code=self._errors.status_for("identification_required"),
                detail=_CHALLENGE_REASON,
                headers={ClientHeaders.CHALLENGE: _CHALLENGE_REASON},
            )
        scope = Scope(self._connection_for(declaration))
        self._errors.respond(self._ops.identify(declaration, scope=scope))
        return scope

    @staticmethod
    def _declaration(request: Request) -> dict[str, object] | None:
        """Read this request's identity headers into a declaration, or ``None``.

        RestCaller is the HTTP adapter: it pulls the headers off the starlette
        request and hands their shape to the one shared :class:`ClientHeaders`
        contract, so ``resolve`` never touches ``request.headers`` directly and the
        header names live in a single place both the client and the Hub read.
        """
        return ClientHeaders.declaration_from(request.headers)

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
