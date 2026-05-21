"""Text-family draw commands — ``TextGlyph``.

``TextGlyph`` renders a string at ``pos`` in ``color``. It composes
``Point2`` and ``Color`` from ``draw_values``. There is no
``thickness`` field — text is glyph-rendered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from punt_lux.protocol.elements.draw_command_kind import DrawCommandKind, WireDict
from punt_lux.protocol.elements.draw_values import WHITE, Color, Point2
from punt_lux.protocol.elements.draw_wire import WireContext

__all__ = ["TextGlyph"]


@dataclass(frozen=True, slots=True)
class TextGlyph:
    """Text glyph at ``pos`` reading the string in ``text``."""

    pos: Point2
    text: str
    color: Color = WHITE
    kind: Literal[DrawCommandKind.TEXT] = DrawCommandKind.TEXT

    def to_dict(self) -> WireDict:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "pos": self.pos.to_list(),
            "text": self.text,
            "color": self.color.to_wire(),
        }

    @classmethod
    def from_wire(cls, d: Mapping[str, object], *, ctx: WireContext) -> Self:
        """Build a ``TextGlyph`` from a wire dict."""
        pos = Point2.from_wire(ctx.require_field(d, "pos"), ctx=ctx, field="pos")
        text = ctx.require_string(ctx.require_field(d, "text"), "text")
        return cls(
            pos=pos,
            text=text,
            color=Color.from_wire_optional(d, ctx=ctx, field="color", default=WHITE),
        )
