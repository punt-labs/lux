# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Shared ImGui arrow-direction lookup for button-family renderers."""

from __future__ import annotations

from typing import Any, ClassVar, Self

from imgui_bundle import imgui

__all__ = ["ArrowDirections"]


class ArrowDirections:
    """Resolve a string arrow name ("left"/"right"/"up"/"down") to ImGui's Dir enum.

    The cache is populated on first use to avoid touching ImGui's enum
    values at module import time (some test harnesses construct the
    class without an active ImGui context).
    """

    _table: ClassVar[dict[str, Any] | None] = None

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def resolve(self, name: str) -> Any | None:
        """Return the ImGui ``Dir`` value for *name*, or ``None`` if unknown."""
        if ArrowDirections._table is None:
            ArrowDirections._table = {
                "left": imgui.Dir.left,
                "right": imgui.Dir.right,
                "up": imgui.Dir.up,
                "down": imgui.Dir.down,
            }
        return ArrowDirections._table.get(name)
