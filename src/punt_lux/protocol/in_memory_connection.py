"""InMemoryConnection — paired-queue duplex for in-process tests.

Per docs/oo-refactor/pr3-v2.1-design.md §5: the in-memory backend for
``LUX_DISPLAY_IN_PROCESS=1`` tests. Exposes the same ``send_line`` /
``iter_lines`` / ``close`` shape as ``LineSocket``.

D7 (design §6): PR 3 consumes this only from
``tests/integration/test_text_outbound_e2e.py``.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.protocol.connection import WireDict

__all__ = ["InMemoryConnection"]


@dataclass(frozen=True, slots=True)
class _Frame:
    """One wire payload travelling through the in-memory queue."""

    payload: dict[str, object]


# Identity-compared sentinel placed on the queue when an end closes.
# A module-level singleton lets ``iter(queue.get, _CLOSE)`` terminate
# without an extra branch, and keeps the module under three classes
# (PY-OO-2) alongside ``_Frame`` and ``InMemoryConnection``.
_CLOSE: Final[object] = object()


type _Item = _Frame | object
type _Endpoint = tuple[
    queue.SimpleQueue[_Item],  # inbound
    queue.SimpleQueue[_Item],  # outbound
    threading.Event,  # self_closed
    threading.Event,  # peer_closed
]


class InMemoryConnection:
    """Paired-queue duplex matching the ``LineSocket`` shape.

    ``send_line`` raises if either end is closed — including the peer.
    A peer-side close arms ``peer_closed`` so the next ``send_line``
    fails loud instead of silently accumulating frames no one will
    read. Construct via ``InMemoryConnection.paired()``.

    The constructor takes a single ``_Endpoint`` tuple — four wires
    that bind one end of the duplex: inbound queue, outbound queue,
    and two ``threading.Event`` flags. This end's ``self_closed`` IS
    the other end's ``peer_closed``, so close-detection is symmetric.
    """

    _endpoint: _Endpoint

    def __new__(cls, endpoint: _Endpoint) -> Self:
        self = super().__new__(cls)
        self._endpoint = endpoint
        return self

    @classmethod
    def paired(cls) -> tuple[Self, Self]:
        """Return two ends of one in-process duplex."""
        a_closed = threading.Event()
        b_closed = threading.Event()
        h2c: queue.SimpleQueue[_Item] = queue.SimpleQueue()
        c2h: queue.SimpleQueue[_Item] = queue.SimpleQueue()
        return cls((h2c, c2h, a_closed, b_closed)), cls((c2h, h2c, b_closed, a_closed))

    def send_line(self, payload: WireDict) -> None:
        """Enqueue ``payload`` for the peer's ``iter_lines``.

        Raises ``RuntimeError`` if this end is closed or if the peer
        has closed — sending into a queue no one will drain is a bug.
        """
        _inbound, outbound, self_closed, peer_closed = self._endpoint
        if self_closed.is_set():
            raise RuntimeError("send on closed InMemoryConnection")
        if peer_closed.is_set():
            raise RuntimeError("peer closed InMemoryConnection")
        outbound.put(_Frame(payload=payload))

    def iter_lines(self) -> Iterator[WireDict]:
        """Yield payloads until the peer closes the connection.

        ``iter(callable, sentinel)`` stops on the identity-matching
        ``_CLOSE`` sentinel, so every yielded item is a ``_Frame``.
        """
        inbound = self._endpoint[0]
        for item in iter(inbound.get, _CLOSE):
            yield cast("_Frame", item).payload

    def close(self) -> None:
        """Mark this end closed and unblock the peer's ``iter_lines``."""
        _inbound, outbound, self_closed, _peer_closed = self._endpoint
        if self_closed.is_set():
            return
        self_closed.set()
        outbound.put(_CLOSE)
