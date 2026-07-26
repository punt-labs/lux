"""Painted geometry with Z-order — a rect plus where it sits in the stack.

A rect alone cannot answer "which of two overlapping things is on top", so the
geometry reply carries Z-order in two levels:

- ``ElementGeometry`` adds ``paint_sequence`` — the order the element painted
  within the frame. Within one window, a higher sequence painted later, so it
  draws on top.
- ``FrameGeometry`` adds ``stack_index`` — the window's position in ImGui's
  window order. Across windows, a higher stack index is in front: an open modal
  sits above the frame beneath it.

An element that is itself a window (window, dialog, modal) carries both — its
paint sequence among the frame's elements and its own window's stack index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self, cast

from punt_lux.protocol.geometry import Rect

__all__ = ["ElementGeometry", "FrameGeometry"]


@dataclass(frozen=True, slots=True)
class ElementGeometry:
    """An element's painted rect, its paint order, and its window's stack index."""

    rect: Rect
    paint_sequence: int
    stack_index: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict the geometry reply carries."""
        return {
            "rect": self.rect.to_dict(),
            "paint_sequence": self.paint_sequence,
            "stack_index": self.stack_index,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Build from a wire dict; a missing or non-integer field raises here."""
        return cls(
            rect=cls.require_rect(d, "rect"),
            paint_sequence=cls.require_int(d, "paint_sequence"),
            stack_index=cls.require_int(d, "stack_index"),
        )

    @staticmethod
    def require_rect(d: dict[str, Any], field: str) -> Rect:
        """Return ``d[field]`` decoded as a ``Rect`` or raise a named ``ValueError``.

        Shared with :class:`FrameGeometry` — both wire values nest a rect the same
        way, so the family decodes it in one place.
        """
        raw = d.get(field)
        if not isinstance(raw, dict):
            msg = (
                f"painted-geometry field {field!r} must be a rect mapping; got {raw!r}"
            )
            raise ValueError(msg)
        return Rect.from_dict(cast("dict[str, Any]", raw))

    @staticmethod
    def require_int(d: dict[str, Any], field: str) -> int:
        """Return ``d[field]`` as an ``int`` or raise; ``bool`` is not an index."""
        raw = d.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int):
            msg = f"painted-geometry field {field!r} must be an integer; got {raw!r}"
            raise ValueError(msg)
        return raw


@dataclass(frozen=True, slots=True)
class FrameGeometry:
    """A frame window's painted rect and its position in ImGui's window order."""

    rect: Rect
    stack_index: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict the geometry reply carries."""
        return {"rect": self.rect.to_dict(), "stack_index": self.stack_index}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Build from a wire dict; a missing or non-integer field raises here."""
        return cls(
            rect=ElementGeometry.require_rect(d, "rect"),
            stack_index=ElementGeometry.require_int(d, "stack_index"),
        )
