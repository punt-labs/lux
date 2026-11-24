"""NumericInputChecks — the range/finiteness/format predicate for a numeric input."""

from __future__ import annotations

import math
import re
from typing import Self, final

__all__ = ["NumericInputChecks"]


@final
class NumericInputChecks:
    """Finiteness, integrality, bounds, step, and format checks for a numeric input."""

    _value: float
    _min: float | None
    _max: float | None
    _step: float | None
    _integer: bool
    _format: str
    __slots__ = tuple(__annotations__)

    def __new__(
        cls,
        *,
        value: float,
        min: float | None,
        max: float | None,
        step: float | None,
        integer: bool,
        format: str,
    ) -> Self:
        self = super().__new__(cls)
        self._value = value
        self._min = min
        self._max = max
        self._step = step
        self._integer = integer
        self._format = format
        return self

    def range_error_messages(self) -> tuple[str, ...]:
        """Return finiteness, integrality, bounds, and step errors (no fail-fast)."""
        nonfinite = self._nonfinite_errors()
        if nonfinite:
            return nonfinite
        return self._integral_errors() + self._bounds_errors() + self._step_errors()

    def format_error_message(self) -> str | None:
        """Return the printf-format error, or None when the format is well-formed."""
        specifiers = "diouxX" if self._integer else "eEfFgGaA"
        conversion = rf"%[-+ #0]*\d*(?:\.\d+)?[hlLjztq]*[{specifiers}]"
        literal = r"(?:[^%]|%%)*"
        if re.fullmatch(rf"{literal}{conversion}{literal}", self._format) is not None:
            return None
        return f"format must be a single printf conversion, got {self._format!r}"

    def all_messages(self) -> tuple[str, ...]:
        """Return every range, finiteness, and format error (well-formedness)."""
        messages = list(self.range_error_messages())
        fmt_error = self.format_error_message()
        if fmt_error is not None:
            messages.append(fmt_error)
        return tuple(messages)

    def sanitized(self, raw: int | float) -> int | float:
        """Return the Hub-valid value the renderer may observe/commit/fire.

        A non-finite overflow collapses to the bound it overflowed (``+inf``->max,
        ``-inf``->min); only with that side unbounded (clamp stays non-finite) or a
        ``NaN`` is the gesture dropped for the element's own validated value.
        """
        low = -math.inf if self._min is None else self._min
        high = math.inf if self._max is None else self._max
        projected = math.nan if math.isnan(raw) else min(high, max(low, raw))
        if math.isfinite(projected):
            projected = int(projected) if self._integer else projected
            substituted = type(self)(
                value=projected,
                min=self._min,
                max=self._max,
                step=self._step,
                integer=self._integer,
                format=self._format,
            )
            if not substituted.range_error_messages():
                return projected
        return int(self._value) if self._integer else self._value

    def _present_fields(self) -> tuple[tuple[str, float], ...]:
        fields: list[tuple[str, float]] = [("value", self._value)]
        for name, v in (("min", self._min), ("max", self._max), ("step", self._step)):
            if v is not None:
                fields.append((name, v))
        return tuple(fields)

    def _nonfinite_errors(self) -> tuple[str, ...]:
        return tuple(
            f"{name} must be finite, got {v!r}"
            for name, v in self._present_fields()
            if not math.isfinite(v)
        )

    def _integral_errors(self) -> tuple[str, ...]:
        if not self._integer:
            return ()
        return tuple(
            f"{name} ({v}) must be a whole number for an integer input"
            for name, v in self._present_fields()
            if not float(v).is_integer()
        )

    def _bounds_errors(self) -> tuple[str, ...]:
        if self._inverted_range():
            return (f"min ({self._min}) must be <= max ({self._max})",)
        if self._value_out_of_range():
            return (f"value ({self._value}) must be in {self._range_text()}",)
        return ()

    def _inverted_range(self) -> bool:
        return self._min is not None and self._max is not None and self._min > self._max

    def _value_out_of_range(self) -> bool:
        below = self._min is not None and self._value < self._min
        above = self._max is not None and self._value > self._max
        return below or above

    def _range_text(self) -> str:
        if self._min is not None and self._max is not None:
            return f"[{self._min}, {self._max}]"
        if self._min is not None:
            return f"[{self._min}, +inf)"
        return f"(-inf, {self._max}]"

    def _step_errors(self) -> tuple[str, ...]:
        if self._step is not None and self._step < 0:
            return (f"step ({self._step}) must be >= 0",)
        return ()
