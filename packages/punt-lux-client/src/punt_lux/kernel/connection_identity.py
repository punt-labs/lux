"""Derive a client's stable ``ConnectionId`` from the identity it declares.

A client that reaches the Hub over more than one transport — REST for its scene
pushes, the WebSocket listen leg for its subscribe stream and menu callbacks —
must own one connection across both, so a callback it registered over REST is
delivered over its WebSocket. The connection id is that shared key: deterministic
in the declared identity fields, so the same identity always resolves to the same
connection and two distinct identities never collide. It is attribution under the
same-user trust model, not a credential.

Both the REST caller and the WebSocket handshake resolve their connection through
:class:`ConnectionSeed` so the two legs cannot drift onto different derivations.

An absent field is absent however it is spelled. A declaration read from headers
omits the key entirely, while one dumped from a
:class:`~punt_lux.wire.model.client_identity.ClientIdentity` carries an explicit
``None`` — and both mean "this client declared no repository". They are folded to
the same seed here, so one identity has one connection id no matter which shape a
caller had it in.

The same holds for the host: a declaration that names none is a client on this
machine, which is what :class:`~punt_lux.wire.model.client_identity.ClientIdentity`
defaults its host to, so a header-less declaration and its validated identity
derive one id.
"""

from __future__ import annotations

from hashlib import blake2s
from typing import TYPE_CHECKING, Self, final

from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.kernel.local_host import LocalHost

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["ConnectionSeed"]

# The identity fields the connection id is derived from, joined on a NUL;
# ClientIdentity's own field validators keep every field NUL-free. The host is a
# seed field because a repository path alone repeats across machines.
_FIELDS = ("kind", "name", "host", "repo", "agent")


@final
class ConnectionSeed:
    """The text one declared identity hashes to its connection id.

    Owns what makes two declarations the same client: which fields count, and
    that an absent field and an explicit ``None`` are one spelling. A declaration
    that names no host is a client on this machine.
    """

    _text: str
    __slots__ = ("_text",)

    def __new__(cls, declaration: Mapping[str, object]) -> Self:
        """Fold ``declaration`` into the seed its fields spell."""
        values = {field: declaration.get(field) or "" for field in _FIELDS}
        values["host"] = values["host"] or LocalHost.name()
        self = super().__new__(cls)
        self._text = "\x00".join(map(str, values.values()))
        return self

    @property
    def connection_id(self) -> ConnectionId:
        """The stable connection id this seed derives, across transports."""
        return ConnectionId(blake2s(self._text.encode(), digest_size=8).hexdigest())
