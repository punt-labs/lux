"""HubIdToken -- a HubId's wire representation, not yet resolved.

The Display only ever holds ``ConnectMessage.hub_id`` (a plain wire string)
for a remote Hub, never a live Python :class:`HubId`. Reconstructing one is
the sole legitimate exception to :attr:`HubId.wire_token`'s "compared for
equality only, never parsed" rule -- kept as its own tiny class, rather than
a method on :class:`HubId` itself, so that already-optimal value type's
interface never carries a parameterized reconstruction method it has no
sibling of comparable weight to amortize against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from punt_lux.domain.hub.hub_id import HubId
from punt_lux.domain.hub.id_separator import ID_SEPARATOR

__all__ = ["HubIdToken"]


@final
@dataclass(frozen=True, slots=True)
class HubIdToken:
    """A ``ConnectMessage.hub_id`` string, before it becomes a real ``HubId``."""

    raw: str

    def resolve(self) -> HubId:
        """Return the ``HubId`` this token names, or raise ``ValueError``.

        ``ID_SEPARATOR`` can never appear in an FQDN, so the split round-trips
        exactly: ``HubIdToken(x.wire_token).resolve() == x`` for every
        ``HubId`` a real ``.current()`` or ``.stub()`` ever produces.
        """
        hostname, separator, pid_text = self.raw.rpartition(ID_SEPARATOR)
        if not separator or not hostname or not pid_text.isdigit():
            msg = f"not a HubId wire token: {self.raw!r}"
            raise ValueError(msg)
        return HubId(hostname, int(pid_text))
