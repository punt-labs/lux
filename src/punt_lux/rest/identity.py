"""RestCaller — resolve each REST request's identity and owning scope.

A REST request declares who it is in ``X-Lux-Client-*`` headers; this resolver
turns that declaration into the :class:`~punt_lux.operations.scope.Scope` the
request's writes own. An identified request records its identity against a
connection derived deterministically from that identity, so the same caller owns
the same scenes across requests. A request that carries no identity is refused
with the ``identification_required`` challenge — a write owns UI, and only a named
caller may — while reads take no scope and stay open to an unnamed caller.

Identity attribution goes through :data:`session_identify_command` for parity
with the MCP surface: adding an audit or invariant check to the command fires
on both surfaces, never one. A read route that took no scope resolves to
:data:`ANONYMOUS_REST` — honestly labelled as an anonymous caller rather than
pretending to be luxd — so a command's ``ctx.identity`` is never a stale global.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final, Self, cast, final

from fastapi import HTTPException
from starlette.requests import Request

from punt_lux.commands import (
    Ctx as CommandCtx,
    SessionOps,
    session_identify as session_identify_command,
)
from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.identity_headers import ClientHeaders
from punt_lux.operations.models.identity import Identified
from punt_lux.operations.scope import Scope

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations import Operations, OpError
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["ANONYMOUS_REST", "RestCaller", "resolve_identity", "resolve_scope"]

# The honestly-labelled fallback identity a read route with no declaration gets.
# Reads take no scope, so a command whose Ctx wraps this identity never attributes
# a write to it -- the label surfaces plainly in introspection instead.
ANONYMOUS_REST: Final = ClientIdentity(kind="cli", name="rest-anonymous")


def resolve_scope(request: Request) -> Scope:
    """FastAPI dependency: the owning scope for a write route, from its identity.

    The mounted :class:`RestSurface` stores its :class:`RestCaller` on ``app.state``,
    so every write route shares one resolver as a single ``scope`` parameter rather
    than threading the resolver through each route and taking the raw request.
    """
    caller = cast("RestCaller", request.app.state.rest_caller)
    return caller.resolve(request)


def resolve_identity(request: Request) -> ClientIdentity:
    """FastAPI dependency: the caller's declared identity, or the anonymous fallback.

    A route that declares this dependency without also declaring ``resolve_scope``
    accepts an anonymous caller (a read); a write route pairs it with the scope
    dependency, so the write is refused before this ever returns a stand-in.
    """
    parsed = ClientHeaders.identity_from(request.headers)
    return parsed if parsed is not None else ANONYMOUS_REST


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

        A named request records its declared identity through
        :data:`session_identify_command` -- the same code path MCP's ``identify``
        runs -- so a future check added to the command fires for both surfaces.
        A request that carries no identity is refused with the
        ``identification_required`` challenge before the command ever runs.
        """
        declaration = self._declaration(request)
        if declaration is None:
            raise HTTPException(
                status_code=self._errors.status_for("identification_required"),
                detail=_CHALLENGE_REASON,
                headers={ClientHeaders.CHALLENGE: _CHALLENGE_REASON},
            )
        scope = Scope(self._connection_for(declaration))
        ctx: CommandCtx[SessionOps] = CommandCtx(ops=self._ops, identity=ANONYMOUS_REST)
        outcome: Identified | OpError = asyncio.run(
            session_identify_command.execute(ctx, declaration, scope=scope)
        )
        self._errors.respond(outcome)
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
        """Derive the stable connection id the declared identity owns.

        Shared with the WebSocket listen leg through :func:`connection_for`, so a
        caller that registers a callback over REST and listens over the WebSocket
        under the same identity resolves to one connection on both.
        """
        return connection_for(declaration)
