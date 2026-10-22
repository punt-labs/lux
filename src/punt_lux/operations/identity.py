"""IdentityOperations — the identify first-call that records who a client is.

A client declares its identity once, and the Hub records the declaration against
the caller's connection. The declaration is validated here, at the boundary: a
bad kind, an empty name, or a non-absolute repo comes back as an
``invalid_request`` naming the field, never a raised exception. Under the
same-user-localhost trust model the Hub verifies nothing beyond well-formedness —
identity is attribution, not access control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from pydantic import ValidationError

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.identity import Identified

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.operations.scope import Scope

__all__ = ["IdentityOperations"]


@final
class IdentityOperations:
    """Record the identity a client declares against its connection."""

    _lifecycle: ClientLifecycle
    _clients: HubClientRegistry
    __slots__ = ("_clients", "_lifecycle")

    def __new__(cls, lifecycle: ClientLifecycle, clients: HubClientRegistry) -> Self:
        self = super().__new__(cls)
        self._lifecycle = lifecycle
        self._clients = clients
        return self

    def identify(
        self,
        declaration: dict[str, object],
        *,
        scope: Scope,
    ) -> Identified | OpError:
        """Validate ``declaration`` into an identity and record it for the caller.

        ``declaration`` carries the raw ``kind``/``name``/``repo``/``agent`` a
        front door received; a malformed one is rejected by field name. On success
        the identity is bound to the caller's connection and echoed back.
        """
        try:
            identity = ClientIdentity.model_validate(declaration)
        except ValidationError as exc:
            return OpError.from_validation(exc)
        self._lifecycle.identify(scope.connection_id, identity)
        return Identified(identity=identity)

    def current(self, scope: Scope) -> ClientIdentity | None:
        """Return the identity already declared for ``scope``'s connection, if any.

        ``None`` is the honest state of a connection that has not yet called
        ``identify`` — genuinely absent, not a give-up: callers that need an
        identity regardless (e.g. a command's ``Ctx``) supply their own
        documented fallback rather than this method inventing one.
        """
        return self._clients.identity_of(scope.connection_id)
