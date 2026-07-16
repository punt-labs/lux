"""NumericInputChecks — the range/finiteness/format predicate for a numeric input.

Composed by ``InputNumberElement`` and judged once for the whole (patchable) field
set at the element boundary — never per setter. It owns the two range operations
the element delegates: ``all_messages`` (well-formedness) and ``clamp``.

Finiteness is a reconciliation precondition: ``NaN`` (the one float where
``x == x`` is false) could never close its optimistic-echo window, so it is
reported alone — other errors against it are noise.
"""

from __future__ import annotations

import math
import re
from typing import Self, final

__all__ = ["NumericInputChecks"]


@final
class NumericInputChecks:
    """Finiteness, integrality, bounds, step, and format checks for a numeric input.

    A value object built fresh from an element's current fields. Integrality is
    enforced here (not just at the widget) because ``input_int`` truncates its
    bounds to ``int``, which could push a commit outside the Hub-re-checked range.
    """

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
        """Return finiteness, integrality, bounds, and step errors (no fail-fast).

        Non-finite values report alone; once finite, the rest report together.
        """
        nonfinite = self._nonfinite_errors()
        if nonfinite:
            return nonfinite
        return self._integral_errors() + self._bounds_errors() + self._step_errors()

    def format_error_message(self) -> str | None:
        """Return the printf-format error, or ``None`` when the format is well-formed.

        Exactly one variant-matching conversion must survive escaped ``%%``
        (``diouxX`` for integer, ``eEfFgGaA`` for float); width/precision stay
        numeric — a ``*`` would read an unsupplied vararg.
        """
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

    def clamp(self, value: int | float) -> int | float:
        """Return ``value`` clamped into ``[min, max]`` (``±inf`` for an absent bound).

        The renderer clamps here before commit; the integer variant returns ``int``.
        """
        low = -math.inf if self._min is None else self._min
        high = math.inf if self._max is None else self._max
        bounded = min(high, max(low, value))
        return int(bounded) if self._integer else bounded

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
        """Return the inverted-range error alone, else any out-of-range error."""
        if self._min is not None and self._max is not None and self._min > self._max:
            return (f"min ({self._min}) must be <= max ({self._max})",)
        below = self._min is not None and self._value < self._min
        above = self._max is not None and self._value > self._max
        if not (below or above):
            return ()
        return (f"value ({self._value}) must be in {self._range_text()}",)

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
