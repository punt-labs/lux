"""DialRef -- what whoever must say which dial failed may ask of it.

A failed request names its dial by handing back something that satisfies this, and
the retirement it asks for is made in the connection that owns the dial; the name
carries no socket, no write and no read. The generation makes its own
(:class:`~punt_lux.domain.hub.generation_ref.GenerationRef`); a test double satisfies
the same shape without being one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.display_connection import DisplayConnection

__all__ = ["DialRef"]


class DialRef(Protocol):
    """One dial, named: how it ended, whether its Display is local, and retiring it."""

    @property
    # PY-TS-14 OK: None until a cause is recorded for the dial's end.
    def ended(self) -> RetireCause | None:
        """The cause recorded for this dial's end; ``None`` while none is."""
        ...

    def reaches_local_display(self) -> bool:
        """Whether the Display behind this dial is this host's own."""
        ...

    def retire_in(self, connection: DisplayConnection, *, cause: RetireCause) -> bool:
        """End this dial in ``connection`` if it is still the current one."""
        ...
