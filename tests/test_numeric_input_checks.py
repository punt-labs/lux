"""NumericInputChecks.sanitized — the renderer's commit guard, in isolation.

``sanitized`` projects a raw widget entry into the Hub-valid value set via
``min(high, max(low, raw))``, makes it integral, and re-checks the result against
the same predicate ``apply_patch`` runs. A non-finite overflow (``±inf``) the
widget can hand back for an entry like ``"1e400"`` collapses to the bound it
overflowed — ``+inf`` to a finite ``max``, ``-inf`` to a finite ``min``. Only when
that side is unbounded (the clamp stays non-finite) or the entry is ``NaN`` (no
bound to pick) is the gesture dropped for the element's own validated value.
Whatever is returned is range-valid, so ``apply_patch``'s re-check never trips.
These tests pin that guarantee for every bound shape, with no imgui seam.
"""

from __future__ import annotations

import math

import pytest

from punt_lux.protocol.elements.numeric_input_checks import NumericInputChecks

_FALLBACK = 5.0


def _checks(
    *,
    min: float | None,
    max: float | None,
    integer: bool = False,
    value: float = _FALLBACK,
    step: float | None = None,
) -> NumericInputChecks:
    """Build a checks value object over a validated field set."""
    fmt = "%d" if integer else "%.3f"
    return NumericInputChecks(
        value=value, min=min, max=max, step=step, integer=integer, format=fmt
    )


class TestSanitizedFiniteProjection:
    @pytest.mark.parametrize(
        ("low", "high", "raw", "expected"),
        [
            (0.0, 100.0, 150.0, 100.0),  # both bounds: over-max clamps down
            (0.0, 100.0, -50.0, 0.0),  # both bounds: under-min clamps up
            (0.0, 100.0, 42.0, 42.0),  # both bounds: in range untouched
            (0.0, None, 1e9, 1e9),  # min only: unbounded above passes through
            (0.0, None, -5.0, 0.0),  # min only: under-min clamps up
            (None, 100.0, 150.0, 100.0),  # max only: over-max clamps down
            (None, 100.0, -1e9, -1e9),  # max only: unbounded below passes through
            (None, None, 42.5, 42.5),  # unbounded: every finite entry is honoured
        ],
    )
    def test_finite_entry_projects_into_range(
        self, low: float | None, high: float | None, raw: float, expected: float
    ) -> None:
        assert _checks(min=low, max=high).sanitized(raw) == expected


class TestSanitizedNonFiniteClampsToBound:
    @pytest.mark.parametrize(
        ("low", "high", "bad", "expected"),
        [
            (0.0, 100.0, math.inf, 100.0),  # +inf overflows a finite max -> max
            (0.0, 100.0, -math.inf, 0.0),  # -inf overflows a finite min -> min
            (0.0, None, -math.inf, 0.0),  # -inf with a finite min -> min
            (None, 100.0, math.inf, 100.0),  # +inf with a finite max -> max
        ],
    )
    def test_overflow_collapses_to_the_bound_it_overflowed(
        self, low: float | None, high: float | None, bad: float, expected: float
    ) -> None:
        # min(high, max(low, ±inf)) already maps the overflow to the finite bound.
        assert _checks(min=low, max=high).sanitized(bad) == expected


class TestSanitizedNonFiniteDropped:
    @pytest.mark.parametrize(
        ("low", "high", "bad"),
        [
            (0.0, None, math.inf),  # +inf, max unbounded -> no bound to clamp it
            (None, 100.0, -math.inf),  # -inf, min unbounded -> no bound to clamp it
            (None, None, math.inf),  # fully open above
            (None, None, -math.inf),  # fully open below
            (0.0, 100.0, math.nan),  # NaN: non-directional, no bound to pick
            (0.0, None, math.nan),
            (None, 100.0, math.nan),
            (None, None, math.nan),
        ],
    )
    def test_unbounded_overflow_or_nan_drops_to_the_validated_value(
        self, low: float | None, high: float | None, bad: float
    ) -> None:
        # No finite bound on the offending side (or a NaN): the gesture is dropped
        # for the element's own validated value, finite and Hub-valid by construction.
        result = _checks(min=low, max=high).sanitized(bad)
        assert result == _FALLBACK
        assert math.isfinite(result)

    def test_result_is_always_range_valid(self) -> None:
        # By construction: whatever sanitized returns passes range_error_messages,
        # so apply_patch's re-check can never trip on it.
        checks = _checks(min=0.0, max=None)
        for raw in (math.inf, -math.inf, math.nan, 1e400, -1e400, 250.0, -3.0):
            projected = checks.sanitized(raw)
            re_checked = _checks(min=0.0, max=None, value=projected)
            assert re_checked.range_error_messages() == ()


class TestSanitizedIntegerVariant:
    def test_over_max_integer_entry_clamps_and_stays_int(self) -> None:
        result = _checks(min=0.0, max=100.0, integer=True).sanitized(150.0)
        assert result == 100
        assert isinstance(result, int)

    def test_in_range_integer_entry_truncates_to_int(self) -> None:
        result = _checks(min=0.0, max=100.0, integer=True).sanitized(42.0)
        assert result == 42
        assert isinstance(result, int)

    def test_overflow_integer_entry_clamps_to_int_bound(self) -> None:
        # +inf on a bounded integer field collapses to the (integral) max, as int.
        result = _checks(min=0.0, max=100.0, integer=True).sanitized(math.inf)
        assert result == 100
        assert isinstance(result, int)

    def test_unbounded_non_finite_integer_entry_drops_to_int_validated_value(
        self,
    ) -> None:
        # int(math.inf) would raise; the finiteness guard makes the cast total and
        # the drop returns the validated value as an ``int`` for the payload.
        result = _checks(min=0.0, max=None, integer=True, value=3.0).sanitized(math.inf)
        assert result == 3
        assert isinstance(result, int)
