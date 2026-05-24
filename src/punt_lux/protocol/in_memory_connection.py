"""InMemoryConnection — paired-queue duplex for in-process tests.

Per docs/oo-refactor/pr3-v2.1-design.md §5: the in-memory backend for
``LUX_DISPLAY_IN_PROCESS=1`` tests. Exposes the same ``send_line`` /
``iter_lines`` / ``close`` shape as ``LineSocket`` so consumers don't
branch on backend.

Built around two ``queue.SimpleQueue`` instances — one carries
hub→client lines, the other carries client→hub. ``paired()`` returns
the two ends already wired so a test can drive both sides in-process
without crossing a socket.

D7 (design §6): PR 3 consumes this only from
``tests/integration/test_text_outbound_e2e.py``; ``DisplayClient`` stays
on its existing length-prefixed wire path until a coordinated flip.
"""

from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.protocol.connection import WireDict

__all__ = ["InMemoryConnection"]


@dataclass(frozen=True, slots=True)
class _Frame:
    """One wire payload travelling through the in-memory queue."""

    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Close:
    """Sentinel that signals the peer has closed; reader should stop."""


type _Item = _Frame | _Close


class InMemoryConnection:
    """Paired-queue duplex matching the ``LineSocket`` shape.

    Each end owns an inbound and an outbound queue. ``send_line`` puts
    onto the outbound queue (the peer's inbound); ``iter_lines`` drains
    the inbound queue until the peer's ``close`` enqueues the close
    sentinel.

    Construct via ``InMemoryConnection.paired()`` rather than directly;
    the paired factory wires the two queues so the ends share them in
    mirrored roles.
    """

    _inbound: queue.SimpleQueue[_Item]
    _outbound: queue.SimpleQueue[_Item]
    _closed: bool

    def __new__(
        cls,
        inbound: queue.SimpleQueue[_Item],
        outbound: queue.SimpleQueue[_Item],
    ) -> Self:
        self = super().__new__(cls)
        self._inbound = inbound
        self._outbound = outbound
        self._closed = False
        return self

    @classmethod
    def paired(cls) -> tuple[Self, Self]:
        """Return two ends of one in-process duplex.

        ``a.send_line`` puts onto ``b.iter_lines``'s queue, and vice
        versa. Either end's ``close`` terminates the other's iteration.
        """
        hub_to_client: queue.SimpleQueue[_Item] = queue.SimpleQueue()
        client_to_hub: queue.SimpleQueue[_Item] = queue.SimpleQueue()
        a = cls(inbound=hub_to_client, outbound=client_to_hub)
        b = cls(inbound=client_to_hub, outbound=hub_to_client)
        return a, b

    def send_line(self, payload: WireDict) -> None:
        """Enqueue ``payload`` for the peer's ``iter_lines``."""
        if self._closed:
            msg = "send on closed InMemoryConnection"
            raise RuntimeError(msg)
        self._outbound.put(_Frame(payload=payload))

    def iter_lines(self) -> Iterator[WireDict]:
        """Yield payloads until the peer closes the connection."""
        while True:
            item = self._inbound.get()
            if isinstance(item, _Close):
                return
            yield item.payload

    def close(self) -> None:
        """Mark this end closed and unblock the peer's ``iter_lines``."""
        if self._closed:
            return
        self._closed = True
        # Tell the peer's reader to stop. The peer iterates ``_inbound``,
        # which is THIS end's outbound queue — that's why we put the
        # sentinel on ``_outbound``.
        self._outbound.put(_Close())
