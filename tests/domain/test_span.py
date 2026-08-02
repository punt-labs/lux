"""Span — a number of seconds, as a person says it.

One value class owns duration rendering so a connected time and a lease length
never drift into two formats.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.span import Span


@pytest.mark.parametrize(
    ("seconds", "rendered"),
    [
        (0.0, "0s"),
        (0.9, "0s"),  # a part-second is not yet a second
        (45.0, "45s"),
        (59.9, "59s"),
        (60.0, "1m 00s"),
        (65.0, "1m 05s"),  # the seconds are padded so the column holds
        (3599.0, "59m 59s"),
        (3600.0, "1h 00m"),
        (11220.0, "3h 07m"),
    ],
)
def test_a_span_reads_the_way_a_person_says_it(seconds: float, rendered: str) -> None:
    assert Span.of(seconds).rendered() == rendered


def test_a_negative_span_is_floored_rather_than_reported() -> None:
    """A clock that went backwards is not a shorter duration; it is a bad clock."""
    assert Span.of(-3.0).rendered() == "0s"
    assert Span.of(-3.0) == Span(0.0)


def test_two_spans_of_one_length_are_equal() -> None:
    assert Span.of(90.0) == Span.of(90.0)
