"""Pending -- the ticket for one reply a dial's sink owes.

Opaque to everyone but the sink that issued it, which keeps the reply and whether a
caller still waits; a holder can only give it back to that sink.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.protocol import Message

__all__ = ["Pending"]


@final
class Pending[K, R: Message]:
    """A ticket for one reply a sink owes: what it must echo, and what it will be."""

    _key: K
    _kind: type[R]
    __slots__ = ("_key", "_kind")

    def __new__(cls, key: K, kind: type[R]) -> Self:
        self = super().__new__(cls)
        self._key = key
        self._kind = kind
        return self

    @property
    def key(self) -> K:
        """What the reply must echo: a ping's ``ts``, an ack's scene id."""
        return self._key

    @property
    def kind(self) -> type[R]:
        """The type of the reply that answers it."""
        return self._kind
