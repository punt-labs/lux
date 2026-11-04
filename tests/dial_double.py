"""A stand-in dial for test fakes that are asked which dial a request used."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.display_connection import DisplayConnection

__all__ = ["FakeDial", "end_fake_dial", "fake_dial"]


@final
class FakeDial:
    """A dial a fake never reads or writes, satisfying ``DialRef`` by its shape.

    The code under test hands it back (``drop(dial)``) and asks how it ended and
    whether its Display is local; nothing retires it, as nothing connects to it.
    """

    # PY-TS-14 OK: None is a dial nothing has ended.
    _ended: RetireCause | None
    _local: bool
    __slots__ = ("_ended", "_local")

    def __new__(
        cls,
        ended: RetireCause | None = None,  # PY-TS-14 OK: a dial nothing has ended
        *,
        local: bool = True,
    ) -> Self:
        self = super().__new__(cls)
        self._ended = ended
        self._local = local
        return self

    @property
    # PY-TS-14 OK: None is a dial nothing has ended.
    def ended(self) -> RetireCause | None:
        """How the dial ended; ``None`` while nothing has ended it."""
        return self._ended

    def end(self, cause: RetireCause) -> None:
        """Record who ended the dial, as a real dial's writer would."""
        self._ended = cause

    def reaches_local_display(self) -> bool:
        """Whether this stand-in stands for a dial to this host's own Display."""
        return self._local

    def retire_in(self, connection: DisplayConnection, *, cause: RetireCause) -> bool:
        """Retire nothing: no connection holds a stand-in dial."""
        del connection, cause
        return False


def fake_dial(
    ended: RetireCause | None = None,  # PY-TS-14 OK: None is a dial nothing has ended
    *,
    cross_host: bool = False,
) -> FakeDial:
    """Return a stand-in for a dial the fake never reads or writes."""
    return FakeDial(ended, local=not cross_host)


def end_fake_dial(dial: FakeDial, cause: RetireCause) -> None:
    """Record on a stand-in dial who ended it, as a real dial's writer would."""
    dial.end(cause)
