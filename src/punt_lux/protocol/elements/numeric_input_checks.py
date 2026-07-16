"""NumericInputChecks — the range/finiteness/format predicate for a numeric input.

Composed by ``InputNumberElement``: because ``value`` / ``min`` / ``max`` / ``step``
are all patchable, the invariant is judged once for the whole field set at the
element boundary — ``validate()`` before render and the ``apply_patch`` re-check —
never per setter. Optional bounds and step skip their comparison when absent
(``None`` = unbounded / no stepper).

Finiteness is the reconciliation-soundness precondition, not a nicety: ``NaN`` is
the one float where ``x == x`` is false, so a committed ``NaN`` could never close
its optimistic-echo window. It is reported alone — integrality or bounds errors
against a non-finite value are noise.
"""

from __future__ import annotations

import math
import re
from typing import Self, final

__all__ = ["NumericInputChecks"]


@final
class NumericInputChecks:
    """Finiteness, integrality, bounds, step, and format checks for a numeric input.

    A value object built fresh from an element's current fields. The integer
    variant renders via ``input_int``, which truncates its bounds to ``int`` —
    so a non-integral bound would let a truncated commit fall outside the range
    the Hub re-checks; that is why integrality is enforced here, not merely at
    the widget.
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

        Non-finite values report alone; once finite, the remaining checks report
        together so a caller sees every degeneracy at once.
        """
        nonfinite = self._nonfinite_errors()
        if nonfinite:
            return nonfinite
        return self._integral_errors() + self._bounds_errors() + self._step_errors()

    def format_error_message(self) -> str | None:
        """Return the printf-format error, or ``None`` when the format is well-formed.

        Exactly one variant-matching conversion must remain after escaped ``%%``
        literals: ``diouxX`` for the integer variant, ``eEfFgGaA`` for float.
        Width/precision are numeric only — a ``*`` would read an unsupplied
        vararg, since only the value is passed.
        """
        specifiers = "diouxX" if self._integer else "eEfFgGaA"
        conversion = rf"%[-+ #0]*\d*(?:\.\d+)?[hlLjztq]*[{specifiers}]"
        literal = r"(?:[^%]|%%)*"
        if re.fullmatch(rf"{literal}{conversion}{literal}", self._format) is not None:
            return None
        return f"format must be a single printf conversion, got {self._format!r}"

    def _present_fields(self) -> tuple[tuple[str, float], ...]:
        """Return ``(name, value)`` for ``value`` plus every present bound and step."""
        fields: list[tuple[str, float]] = [("value", self._value)]
        for name, v in (("min", self._min), ("max", self._max), ("step", self._step)):
            if v is not None:
                fields.append((name, v))
        return tuple(fields)

    def _nonfinite_errors(self) -> tuple[str, ...]:
        """Return an error per non-finite present field (``value`` / bounds / step)."""
        return tuple(
            f"{name} must be finite, got {v!r}"
            for name, v in self._present_fields()
            if not math.isfinite(v)
        )

    def _integral_errors(self) -> tuple[str, ...]:
        """Return an error per non-integral present field on the integer variant."""
        if not self._integer:
            return ()
        return tuple(
            f"{name} ({v}) must be a whole number for an integer input"
            for name, v in self._present_fields()
            if not float(v).is_integer()
        )

    def _bounds_errors(self) -> tuple[str, ...]:
        """Return the inverted-range error alone, else any out-of-range error.

        A missing bound imposes no constraint on that side; an in-range check
        against an inverted ``[min, max]`` would only add noise.
        """
        if self._min is not None and self._max is not None and self._min > self._max:
            return (f"min ({self._min}) must be <= max ({self._max})",)
        below = self._min is not None and self._value < self._min
        above = self._max is not None and self._value > self._max
        if not (below or above):
            return ()
        return (f"value ({self._value}) must be in {self._range_text()}",)

    def _range_text(self) -> str:
        """Return a readable description of the present bounds for an error."""
        if self._min is not None and self._max is not None:
            return f"[{self._min}, {self._max}]"
        if self._min is not None:
            return f"[{self._min}, +inf)"
        return f"(-inf, {self._max}]"

    def _step_errors(self) -> tuple[str, ...]:
        """Return the negative-step error, if any; ``0`` is the 'no buttons' value."""
        if self._step is not None and self._step < 0:
            return (f"step ({self._step}) must be >= 0",)
        return ()
