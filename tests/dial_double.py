"""A stand-in dial for test fakes that are asked which dial a request used."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_ref import DialRef

__all__ = ["fake_dial"]


@final
class _StandInDial:
    """A token that is only handed back, and charged with a death once."""

    _is_blamed: bool
    __slots__ = ("_is_blamed",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._is_blamed = False
        return self

    @property
    def is_blamed(self) -> bool:
        return self._is_blamed

    def claim_blame(self) -> bool:
        claimed = not self._is_blamed
        self._is_blamed = True
        return claimed


def fake_dial() -> DialRef:
    """Return an opaque token standing for a dial the fake never reads or writes.

    The code under test only hands it back (``drop(dial)``) or charges a death to
    it, so a stand-in with no socket behind it serves for a real
    :class:`DialRef` and the dial behind it.
    """
    return cast("DialRef", _StandInDial())
