"""The display connection an operation proxies through — luxd's one leg.

Every display-fact operation reaches the running display over this port: the
same single connection the replicator already owns. The port hides the socket,
the bounded send, and the reconnect policy behind two calls that each return a
:class:`DisplayReply`. The concrete implementation lives in the Hub layer and is
injected at the composition root, so nothing under ``operations/`` names the
``DisplayClient``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.operations.display_reply import DisplayReply

__all__ = ["DisplayPort"]


@runtime_checkable
class DisplayPort(Protocol):
    """luxd's one bounded connection to the display, as an operation sees it."""

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        """Proxy a query to the display and return its bounded reply."""
        ...

    # wait is float | None: None means "use the connection's standing recv
    # budget" — the documented absence contract, not a failure sentinel.
    def ping(self, wait: float | None) -> DisplayReply:
        """Round-trip a ping bounded by ``wait`` seconds (``None`` = default budget).

        A reply payload carries the measured ``rtt_seconds``.
        """
        ...
