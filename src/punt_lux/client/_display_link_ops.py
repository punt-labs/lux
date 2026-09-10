"""``DisplayLinkOps`` -- the bare ``get_link`` shape ``_RestTransport`` satisfies.

Split from :mod:`punt_lux.client._sync_ops` (PY-IC-9: protocols live in their
own module), mirroring :mod:`punt_lux.client._callback_ops`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.operations import OpError
    from punt_lux.operations.models.display_link import DisplayLinkState

__all__ = ["DisplayLinkOps"]


@runtime_checkable
class DisplayLinkOps(Protocol):
    """The Hub's observed display-link state, read with no display round trip."""

    def get_link(self) -> DisplayLinkState | OpError:
        """Return the connected/disconnected link state, or a transport fault.

        The Hub-side classification never faults (:meth:`DisplayLinkOperations.
        get_link`); ``OpError`` here covers only this transport leg -- an
        unreachable luxd or an unparseable reply.
        """
        ...
