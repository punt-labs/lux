"""DialRef -- an opaque name for one dial, for whoever must say which one failed.

A request that fails says which dial it failed on by handing back this reference,
and the retirement it asks for is made in the connection that owns the dial: the
reference carries no socket, no write and no read, so naming a dial confers no
power over it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection

__all__ = ["DialRef"]


@final
class DialRef:
    """One dial, named and nothing more."""

    _generation: DialGeneration
    __slots__ = ("_generation",)

    def __new__(cls, generation: DialGeneration) -> Self:
        self = super().__new__(cls)
        self._generation = generation
        return self

    def retire_in(self, connection: DisplayConnection, *, cause: RetireCause) -> bool:
        """Retire this dial in ``connection`` if it is still the current one.

        Whether it was: a dial a redial replaced is already gone, and its successor
        is not touched.
        """
        return connection.close_if_current(self._generation, cause=cause)
