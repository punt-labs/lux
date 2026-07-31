"""Derive a client's stable ``ConnectionId`` from the identity it declares.

A client that reaches the Hub over more than one transport — REST for its scene
pushes, the WebSocket listen leg for its subscribe stream and menu callbacks —
must own one connection across both, so a callback it registered over REST is
delivered over its WebSocket. The connection id is that shared key: deterministic
in the declared identity fields, so the same identity always resolves to the same
connection and two distinct identities never collide. It is attribution under the
same-user trust model, not a credential.

Both the REST caller and the WebSocket handshake resolve their connection through
:func:`connection_for` so the two legs cannot drift onto different derivations.

An absent field is absent however it is spelled. A declaration read from headers
omits the key entirely, while one dumped from a
:class:`~punt_lux.domain.hub.client_identity.ClientIdentity` carries an explicit
``None`` — and both mean "this client declared no repository". They are folded to
the same seed here, so one identity has one connection id no matter which shape a
caller had it in.
"""

from __future__ import annotations

from hashlib import blake2s
from typing import TYPE_CHECKING

from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["connection_for"]

# The identity fields the connection id is derived from, joined on a NUL that no
# field value contains, so distinct identities cannot collide by concatenation.
_FIELDS = ("kind", "name", "repo", "agent")


def connection_for(declaration: Mapping[str, object]) -> ConnectionId:
    """Derive the stable connection id a declared identity owns across transports."""
    seed = "\x00".join(
        "" if (value := declaration.get(field)) is None else str(value)
        for field in _FIELDS
    )
    return ConnectionId(blake2s(seed.encode(), digest_size=8).hexdigest())
