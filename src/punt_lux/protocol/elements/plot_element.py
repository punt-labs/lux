"""``PlotElement`` — 2D chart with one or more data series.

``series`` is still ``list[dict[str, Any]]`` — the same procedural
anti-pattern the draw-command surface inherited and shed.  A follow-up
tightens this the same way (typed series classes + Protocol).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Self

__all__ = ["PlotElement"]


@dataclass(frozen=True, slots=True)
class PlotElement:
    """A 2D plot with one or more data series (line, scatter, bar)."""

    id: str
    kind: Literal["plot"] = "plot"
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    width: float = -1  # -1 = auto-fill available width
    height: float = 300
    series: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    tooltip: str | None = None  # PY-TS-14: genuinely optional UI text

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict form."""
        return {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "width": self.width,
            "height": self.height,
            "series": self.series,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Build a ``PlotElement`` from a wire dict."""
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            x_label=d.get("x_label", ""),
            y_label=d.get("y_label", ""),
            width=d.get("width", -1),
            height=d.get("height", 300),
            series=d.get("series", []),
        )
