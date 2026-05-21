"""Graphics elements — 2D canvas (Draw) and chart (Plot).

``DrawElement.commands`` is a tuple of typed ``DrawCommand`` instances
(``LineCmd``, ``RectCmd``, ``CircleCmd``, …) — not a list of untyped
wire dicts.  The wire-decode boundary is the ``DrawCommandDecoder``;
the renderer reads typed attributes directly.

``PlotElement.series`` is still ``list[dict[str, Any]]`` — same
procedural anti-pattern as the original ``DrawElement.commands``.
Tracked separately as a follow-up; the scope of this work is the
draw-command surface.

Each element class owns its own ``to_dict`` / ``from_dict`` codec
(PY-OO-5: data and behavior together).  ``register_codecs`` binds
those methods into the project-wide ``ElementCodec`` table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Self, cast

from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.draw_command_kind import DrawCommand, WireDict
from punt_lux.protocol.elements.draw_decoder import DrawCommandDecoder

__all__ = [
    "DrawElement",
    "PlotElement",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class DrawElement:
    """A 2D canvas with typed draw commands.

    ``commands`` is a tuple of ``DrawCommand`` instances. Wire decoding
    runs each command dict through ``DrawCommandDecoder.default()``,
    which raises ``ValueError`` on any malformed input — the renderer
    never sees a dict and cannot silently default.
    """

    id: str
    kind: Literal["draw"] = "draw"
    width: int = 400
    height: int = 300
    bg_color: str | None = None  # PY-TS-14: absent = "use renderer default"
    commands: tuple[DrawCommand, ...] = ()
    tooltip: str | None = None  # PY-TS-14: genuinely optional UI text

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict form."""
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "commands": [cmd.to_dict() for cmd in self.commands],
        }
        if self.bg_color is not None:
            d["bg_color"] = self.bg_color
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Build a ``DrawElement`` from a wire dict.

        Decodes every command via ``DrawCommandDecoder.default()`` —
        any malformed command raises ``ValueError`` here, before the
        element reaches the renderer.
        """
        raw_commands = d.get("commands", ())
        if not isinstance(raw_commands, list | tuple):
            msg = (
                f"DrawElement 'commands' must be a list or tuple; got {raw_commands!r}"
            )
            raise ValueError(msg)
        # raw_commands is a list/tuple from JSON — pyright sees list[Unknown]
        # without an explicit element cast. Each element is narrowed by
        # _require_wire_dict, which raises on non-dicts.
        raw_seq = cast("list[object] | tuple[object, ...]", raw_commands)
        decoder = DrawCommandDecoder.default()
        commands: tuple[DrawCommand, ...] = tuple(
            decoder.decode(_require_wire_dict(c, i), i) for i, c in enumerate(raw_seq)
        )
        return cls(
            id=d["id"],
            width=d.get("width", 400),
            height=d.get("height", 300),
            bg_color=d.get("bg_color"),
            commands=commands,
        )


@dataclass(frozen=True, slots=True)
class PlotElement:
    """A 2D plot with one or more data series (line, scatter, bar).

    ``series`` remains ``list[dict[str, Any]]`` — same anti-pattern as
    the original draw commands.  Follow-up: tighten this the same way
    once the draw-command surface lands.
    """

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


def _require_wire_dict(raw: object, index: int) -> WireDict:
    """Narrow each command-list entry to a wire dict; raise on mismatch.

    Module-private helper used only by ``DrawElement.from_dict``; not a
    method on ``DrawElement`` because it runs *before* an instance
    exists and operates on the untyped wire boundary.
    """
    if not isinstance(raw, dict):
        msg = (
            f"DrawElement command at index {index} must be a dict; "
            f"got {type(raw).__name__}: {raw!r}"
        )
        raise ValueError(msg)
    # JSON-sourced dict — keys are strings, values are arbitrary JSON types.
    # WireDict is dict[str, Any] (justified at the alias definition).
    return cast("WireDict", raw)


def register_codecs(register: Register) -> None:
    """Register this module's element codecs into an ElementCodec.

    Each element class owns its ``to_dict`` and ``from_dict`` — the
    callbacks here are direct method references, not module-level
    wrappers.
    """
    register("draw", DrawElement, DrawElement.to_dict, DrawElement.from_dict)
    register("plot", PlotElement, PlotElement.to_dict, PlotElement.from_dict)
