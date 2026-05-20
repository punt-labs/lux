"""Graphics elements — 2D canvas (Draw) and chart (Plot)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "DrawElement",
    "PlotElement",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class DrawElement:
    """A 2D canvas with draw commands (line, rect, circle, etc.)."""

    id: str
    kind: Literal["draw"] = "draw"
    width: int = 400
    height: int = 300
    bg_color: str | None = None
    commands: list[dict[str, Any]] = field(
        default_factory=lambda: list[dict[str, Any]]()
    )
    tooltip: str | None = None


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
    tooltip: str | None = None


def _draw_to_dict(elem: DrawElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "width": elem.width,
        "height": elem.height,
        "commands": elem.commands,
    }
    if elem.bg_color is not None:
        d["bg_color"] = elem.bg_color
    return d


def _plot_to_dict(elem: PlotElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "title": elem.title,
        "x_label": elem.x_label,
        "y_label": elem.y_label,
        "width": elem.width,
        "height": elem.height,
        "series": elem.series,
    }


def _draw_from_dict(d: dict[str, Any]) -> DrawElement:
    return DrawElement(
        id=d["id"],
        width=d.get("width", 400),
        height=d.get("height", 300),
        bg_color=d.get("bg_color"),
        commands=d.get("commands", []),
    )


def _plot_from_dict(d: dict[str, Any]) -> PlotElement:
    return PlotElement(
        id=d["id"],
        title=d.get("title", ""),
        x_label=d.get("x_label", ""),
        y_label=d.get("y_label", ""),
        width=d.get("width", -1),
        height=d.get("height", 300),
        series=d.get("series", []),
    )


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's element codecs into an ElementCodec."""
    register("draw", DrawElement, _draw_to_dict, _draw_from_dict)
    register("plot", PlotElement, _plot_to_dict, _plot_from_dict)
