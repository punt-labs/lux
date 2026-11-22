"""PlotSeries — one typed data series in a ``plot`` element.

A plot's series are a value family, not elements — the same composition ruling
the draw-command and tree-node families follow. The wire form
``{"label": "y", "type": "line", "x": [...], "y": [...]}`` decodes into a typed
``PlotSeries`` at the boundary (PY-EH-1): a non-string ``label`` (the exact
payload that used to raise a ``TypeError`` mid-render and take the display down),
an unknown ``type``, or a non-numeric coordinate raises ``ValueError`` before any
``PlotElement`` is built. The one invariant a typed series can still violate —
``x`` and ``y`` of unequal length — is reported by ``PlotElement.validate`` so
every ragged series surfaces at once rather than faulting the renderer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast, final, get_args

__all__ = ["PlotSeries", "SeriesType"]

type SeriesType = Literal["line", "scatter", "bar"]
_SERIES_TYPES: tuple[SeriesType, ...] = get_args(SeriesType.__value__)


@final
@dataclass(frozen=True, slots=True)
class PlotSeries:
    """One data series: a ``label``, a plot ``type``, and paired ``x``/``y``."""

    label: str
    series_type: SeriesType
    x: tuple[float, ...]
    y: tuple[float, ...]

    @property
    def is_ragged(self) -> bool:
        """Return whether ``x`` and ``y`` differ in length (an unplottable pair)."""
        return len(self.x) != len(self.y)

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire mapping for this series."""
        return {
            "label": self.label,
            "type": self.series_type,
            "x": list(self.x),
            "y": list(self.y),
        }

    @classmethod
    def decode_all(cls, raw: object, where: str) -> tuple[PlotSeries, ...]:
        """Decode a wire series list to typed series, raising on the first bad one.

        ``where`` names the position in error messages (e.g. ``series``) so a
        malformed series points the agent at the offending entry.
        """
        if not isinstance(raw, list):
            msg = f"{where} must be a list of series; got {type(raw).__name__}"
            raise ValueError(msg)
        seq = cast("list[object]", raw)
        return tuple(
            cls._decode_one(item, f"{where}[{i}]") for i, item in enumerate(seq)
        )

    @classmethod
    def _decode_one(cls, raw: object, where: str) -> PlotSeries:
        """Decode one wire series mapping, validating every field's type."""
        if not isinstance(raw, Mapping):
            msg = f"{where} must be a mapping; got {type(raw).__name__}"
            raise ValueError(msg)
        series = cast("Mapping[str, object]", raw)
        return cls(
            label=cls._require_str(series.get("label", "data"), f"{where}.label"),
            series_type=cls._require_type(series.get("type", "line"), f"{where}.type"),
            x=cls._require_numbers(series.get("x", []), f"{where}.x"),
            y=cls._require_numbers(series.get("y", []), f"{where}.y"),
        )

    @staticmethod
    def _require_str(value: object, where: str) -> str:
        """Return ``value`` as a str or raise — the label crash-guard at decode."""
        if not isinstance(value, str):
            msg = f"{where} must be a string; got {type(value).__name__}"
            raise ValueError(msg)
        return value

    @staticmethod
    def _require_type(value: object, where: str) -> SeriesType:
        """Return ``value`` as a known series type or raise."""
        if value not in _SERIES_TYPES:
            msg = f"{where} must be one of {_SERIES_TYPES}; got {value!r}"
            raise ValueError(msg)
        return value

    @staticmethod
    def _require_numbers(value: object, where: str) -> tuple[float, ...]:
        """Return ``value`` as a tuple of floats or raise (``bool`` rejected)."""
        if not isinstance(value, list):
            msg = f"{where} must be a list of numbers; got {type(value).__name__}"
            raise ValueError(msg)
        seq = cast("list[object]", value)
        out: list[float] = []
        for i, item in enumerate(seq):
            if isinstance(item, bool) or not isinstance(item, int | float):
                msg = f"{where}[{i}] must be a number; got {type(item).__name__}"
                raise ValueError(msg)
            out.append(float(item))
        return tuple(out)
