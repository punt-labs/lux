"""A stand-in dial for test fakes that are asked which dial a request used."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_ref import DialRef

__all__ = ["fake_dial"]


def fake_dial() -> DialRef:
    """Return an opaque token standing for a dial the fake never reads or writes.

    The code under test only hands it back (``drop(dial)``), so a bare object
    stands in for a real :class:`DialRef` and the dial behind it.
    """
    return cast("DialRef", object())
