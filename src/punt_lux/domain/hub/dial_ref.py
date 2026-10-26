"""DialRef -- an opaque name for one dial, for whoever must say which one failed.

A request that fails says which dial it failed on by handing back this reference,
and the retirement it asks for is made in the connection that owns the dial: the
reference carries no socket, no write and no read, so naming a dial confers no
power over it; only the generation makes one, of itself (``DialGeneration.ref``). Two
references to one dial are equal, so whoever remembers a dial can tell it again.
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

    def __eq__(self, other: object) -> bool:
        """Two references name the same dial when they name the same generation."""
        if not isinstance(other, DialRef):
            return NotImplemented
        return self._generation is other._generation

    def __hash__(self) -> int:
        return id(self._generation)

    @property
    # PY-TS-14 OK: None until a cause is recorded for the dial's end.
    def ended(self) -> RetireCause | None:
        """The cause recorded for this dial's end; ``None`` while none is.

        A read, no power over the dial: whoever healed after a failure asks *why* the
        dial ended, and the dial's own record answers, not the exception it raised.
        """
        return self._generation.ended

    @property
    def is_cross_host(self) -> bool:
        """Whether this dial reaches a Display on another host (TCP and mTLS)."""
        return self._generation.is_cross_host

    def retire_in(self, connection: DisplayConnection, *, cause: RetireCause) -> bool:
        """End this dial in ``connection`` if it is still the current one.

        Whether this call did: a dial a redial replaced is already gone, and its
        successor is not touched. A display end or an unresponsive end is settled by
        the dial's reader, not here (see :meth:`DisplayConnection.retire`).
        """
        return connection.retire(self._generation, cause=cause)
