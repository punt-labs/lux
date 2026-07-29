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
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.operations.scope import Scope

__all__ = ["IdentityOperations"]


@final
class IdentityOperations:
    """Record the identity a client declares against its connection."""

    _display: HubDisplay
    __slots__ = ("_display",)

    def __new__(cls, display: HubDisplay) -> Self:
        self = super().__new__(cls)
        self._display = display
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
        self._display.identify_client(scope.connection_id, identity)
        return Identified(identity=identity)
