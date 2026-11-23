"""GenerationRef -- the name one dial generation gives itself, and no power over it.

A request that fails says which dial it failed on by handing back this reference, and
the retirement it asks for is made in the connection that owns the dial: the reference
carries no socket, no write and no read, so naming a dial confers no power over it;
only the generation makes one, of itself (``DialGeneration.ref``). Two references to
one dial are equal, so whoever remembers a dial can tell it again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, final
from uuid import uuid4

if TYPE_CHECKING:
    from punt_lux.hub.connection_closed import RetireCause
    from punt_lux.hub.dial_generation import DialGeneration
    from punt_lux.hub.display_connection import DisplayConnection

__all__ = ["GenerationRef"]


@final
@dataclass(frozen=True, slots=True)
class GenerationRef:
    """One dial generation, named and nothing more."""

    _generation: DialGeneration
    _token: str = field(default_factory=lambda: uuid4().hex, compare=False)

    def __str__(self) -> str:
        return self._token

    @property
    # PY-TS-14 OK: None until a cause is recorded for the dial's end.
    def ended(self) -> RetireCause | None:
        """The cause recorded for this dial's end; ``None`` while none is.

        A read, no power over the dial: whoever healed after a failure asks *why* the
        dial ended, and the dial's own record answers, not the exception it raised.
        """
        return self._generation.ended

    def reaches_local_display(self) -> bool:
        """Whether the Display behind this dial is this host's own (not a TLS dial)."""
        return not self._generation.is_tls

    def retire_in(self, connection: DisplayConnection, *, cause: RetireCause) -> bool:
        """Retire only the named dial, if the connection still owns it."""
        return connection.retire(self._generation, cause=cause)
