"""Drained: bytes, the stream's end, or nothing more -- never two at once."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.drain_result import Drained
from punt_lux.domain.hub.invalid_drain_error import InvalidDrainError
from punt_lux.domain.programmer_error import ProgrammerError


def test_bytes_and_the_end_at_once_are_refused_when_made() -> None:
    with pytest.raises(InvalidDrainError):
        Drained(b"x", ended=True)


def test_the_refusal_is_a_programmer_error() -> None:
    assert issubclass(InvalidDrainError, ProgrammerError)


def test_each_of_the_three_answers_is_made_by_its_own_name() -> None:
    assert (Drained.holding(b"x"), Drained.quiet(), Drained.end()) == (
        Drained(b"x", ended=False),
        Drained(b"", ended=False),
        Drained(b"", ended=True),
    )
