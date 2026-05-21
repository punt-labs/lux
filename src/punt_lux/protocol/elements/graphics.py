"""``DrawElement`` — 2D canvas with typed draw commands.

``commands`` is a tuple of ``DrawCommand`` instances.  Wire decoding
runs each command dict through ``DrawCommandDecoder.default()``, which
raises ``ValueError`` on any malformed input — the renderer never sees
a dict and cannot silently default.

``PlotElement`` lives in the sibling ``plot_element`` module.  The
``register_codecs`` callback here binds both element classes into the
project-wide ``ElementCodec`` table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Self, cast

from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.draw_command_kind import DrawCommand, WireDict
from punt_lux.protocol.elements.draw_decoder import DrawCommandDecoder
from punt_lux.protocol.elements.plot_element import PlotElement

__all__ = ["DrawElement", "PlotElement", "register_codecs"]


@dataclass(frozen=True, slots=True)
class DrawElement:
    """A 2D canvas with typed draw commands."""

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

        Decodes each command via ``DrawCommandDecoder.default()`` — any
        malformed command raises ``ValueError`` here, before the
        element reaches the renderer.
        """
        raw_commands = d.get("commands", ())
        if not isinstance(raw_commands, list | tuple):
            msg = (
                f"DrawElement 'commands' must be a list or tuple; got {raw_commands!r}"
            )
            raise ValueError(msg)
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


def _require_wire_dict(raw: object, index: int) -> WireDict:
    """Narrow a command-list entry to a wire dict; raise on mismatch.

    Module-private — used only by ``DrawElement.from_dict``; runs at
    the wire boundary before any instance exists.
    """
    if not isinstance(raw, dict):
        msg = (
            f"DrawElement command at index {index} must be a dict; "
            f"got {type(raw).__name__}: {raw!r}"
        )
        raise ValueError(msg)
    return cast("WireDict", raw)


def register_codecs(register: Register) -> None:
    """Register the Draw and Plot codecs into an ``ElementCodec``."""
    register("draw", DrawElement, DrawElement.to_dict, DrawElement.from_dict)
    register("plot", PlotElement, PlotElement.to_dict, PlotElement.from_dict)
