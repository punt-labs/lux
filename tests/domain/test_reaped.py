"""Reaped -- what one sweep removed, and which survivors it retitled."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.reaped import Reaped
from punt_lux.domain.ids import ConnectionId

_A = ConnectionId("a")
_B = ConnectionId("b")


def test_survivors_may_be_relabelled_when_others_lapsed() -> None:
    reaped = Reaped(frozenset({_A}), frozenset({_B}))

    assert (reaped.lapsed, reaped.relabelled) == (frozenset({_A}), frozenset({_B}))


def test_an_empty_sweep_is_valid() -> None:
    assert Reaped(frozenset(), frozenset()).lapsed == frozenset()


def test_a_lapsed_connection_cannot_also_be_relabelled() -> None:
    with pytest.raises(ValueError, match="cannot be relabelled"):
        Reaped(frozenset({_A}), frozenset({_A, _B}))
