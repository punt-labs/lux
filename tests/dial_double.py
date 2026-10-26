"""A stand-in dial for test fakes that are asked which dial a request used."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_ref import DialRef

__all__ = ["end_fake_dial", "fake_dial"]


@final
class _FakeDial:
    """What a fake is asked about a dial: how it ended, and where it reaches."""

    ended: RetireCause | None  # PY-TS-14 OK: None is a dial nothing has ended
    is_cross_host: bool

    def __init__(self, ended: RetireCause | None, *, cross_host: bool) -> None:
        self.ended = ended
        self.is_cross_host = cross_host


def fake_dial(
    ended: RetireCause | None = None,  # PY-TS-14 OK: None is a dial nothing has ended
    *,
    cross_host: bool = False,
) -> DialRef:
    """Return an opaque token standing for a dial the fake never reads or writes.

    The code under test hands it back (``drop(dial)``) and asks how it ended and
    whether it reaches another host, so a stand-in with just those answers takes the
    place of a real :class:`DialRef` and the dial behind it.
    """
    return cast("DialRef", _FakeDial(ended, cross_host=cross_host))


def end_fake_dial(dial: DialRef, cause: RetireCause) -> None:
    """Record on a stand-in dial who ended it, as a real dial's writer would."""
    cast("_FakeDial", dial).ended = cause
