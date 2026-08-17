"""ConnectionScopedId — a caller-chosen id, namespaced to who chose it.

The store key a scene or frame is installed under is never the raw string a
client submitted. It is this composite, so two connections can never alias
the same store key even when they submit the identical raw string — the
collision is unrepresentable, not merely rejected.

Mirrors :class:`~punt_lux.domain.hub.session_callback.CallbackInvocation`'s
menu-leaf-id composition, which closed the identical class of collision for
menu callbacks under DES-058/DES-067. This class exists because scene and
frame ids never received the same treatment (DES-086).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Self, final

from punt_lux.domain.hub.id_separator import ID_SEPARATOR
from punt_lux.domain.ids import ConnectionId

__all__ = ["ConnectionScopedId"]

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True, slots=True)
class ConnectionScopedId:
    """A caller-local id, composed with the connection that owns it.

    ``local_id`` must be non-blank and must not carry :data:`ID_SEPARATOR` —
    a control character no honest caller-chosen id ever contains — so the
    composed form always round-trips and two connections can never construct
    the identical composed key from two different raw strings.
    """

    connection_id: ConnectionId
    local_id: str

    def __post_init__(self) -> None:
        if not self.local_id.strip():
            msg = "local id must be a non-empty, non-blank id"
            raise ValueError(msg)
        if ID_SEPARATOR in self.local_id:
            msg = "local id must not contain the unit separator"
            raise ValueError(msg)

    def __str__(self) -> str:
        return f"{self.connection_id}{ID_SEPARATOR}{self.local_id}"

    @classmethod
    def compose(cls, connection_id: ConnectionId, local_id: str) -> str:
        """Return the namespaced store-key string for ``local_id``."""
        return str(cls(connection_id, local_id))

    @classmethod
    def from_composed(cls, composed: str) -> Self:
        """Parse a store key back into its connection and local id.

        Splits on the first :data:`ID_SEPARATOR` — the same shape
        :meth:`~punt_lux.domain.hub.session_callback.CallbackInvocation.from_menu_id`
        parses a leaf id with. Raises ``ValueError`` for a string that never
        went through :meth:`compose`.
        """
        connection, separator, local_id = composed.partition(ID_SEPARATOR)
        if not separator or not connection or not local_id:
            msg = f"not a connection-scoped id: {composed!r}"
            raise ValueError(msg)
        return cls(ConnectionId(connection), local_id)

    @classmethod
    def local_id_of(cls, composed: str) -> str:
        """Return the caller's own label for a store key, composed or not.

        Every scene or frame the ops-layer write path installs is composed
        (DES-086), so this is the caller's raw name in the common case. A key
        installed through a lower-level API directly — outside the choke
        point composition runs through — carries no separator at all; its own
        raw key is the closest thing to a caller label it has, so that is
        what is reported rather than raising. That path is also a DES-086
        invariant violation worth knowing about, so it is logged, not
        silently absorbed.
        """
        try:
            return cls.from_composed(composed).local_id
        except ValueError:
            logger.warning(
                "non-composed store key at introspection boundary: %r", composed
            )
            return composed
