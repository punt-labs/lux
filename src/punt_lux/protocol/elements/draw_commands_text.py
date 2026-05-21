"""Text-family draw commands — ``TextCmd``.

``TextCmd`` renders a string at ``pos`` in ``color``. It composes
``Point2`` and ``Color`` from ``draw_values``. There is no
``thickness`` field — text is glyph-rendered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from punt_lux.protocol.elements.draw_command_kind import DrawCommandKind
from punt_lux.protocol.elements.draw_values import WHITE, Color, Point2

__all__ = ["TextCmd"]


@dataclass(frozen=True, slots=True)
class TextCmd:
    """Text glyph at ``pos`` reading the string in ``text``."""

    pos: Point2
    text: str
    color: Color = WHITE
    kind: Literal[DrawCommandKind.TEXT] = DrawCommandKind.TEXT

    def to_dict(self) -> dict[str, Any]:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "pos": self.pos.to_list(),
            "text": self.text,
            "color": self.color.to_wire(),
        }
