"""Value objects for a window's chrome — its placement and its flag set.

A ``window`` carries two cohesive shapes that would otherwise be a dozen flat
fields on the element: where it opens (:class:`WindowPlacement`) and which
ImGui window behaviours are disabled (:class:`WindowFlags`). Each owns its own
flat-wire mapping (``from_wire`` / ``to_wire``) so the element and its codec
compose the shapes rather than juggling the scalars (PY-IC-1, PY-OO-5). Neither
imports ImGui — the display adapter reads ``WindowFlags.active_names`` and folds
the mask, keeping the renderer dependency out of the protocol layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from punt_lux.protocol.elements.patch_field import PatchField

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["WindowFlags", "WindowPlacement"]


@dataclass(frozen=True, slots=True)
class WindowPlacement:
    """Where a window first opens: its top-left corner and its size.

    These are the *initial* values an agent seeds; once shown, drag and resize
    are Display-local and never re-pushed, so the Hub keeps only this seed.
    """

    x: float = 50.0
    y: float = 50.0
    width: float = 300.0
    height: float = 200.0

    @classmethod
    def from_wire(cls, d: Mapping[str, object]) -> WindowPlacement:
        """Read the placement scalars from a wire dict, defaulting each."""
        return cls(
            x=PatchField("x").as_number(d.get("x", 50.0)),
            y=PatchField("y").as_number(d.get("y", 50.0)),
            width=PatchField("width").as_number(d.get("width", 300.0)),
            height=PatchField("height").as_number(d.get("height", 200.0)),
        )

    def to_wire(self) -> dict[str, object]:
        """Return the placement as its four flat wire keys."""
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True, slots=True)
class WindowFlags:
    """Which ImGui window behaviours are disabled (or auto-sizing is on).

    Each flag is ``False`` by default (the behaviour is enabled); the wire omits
    a flag that is off, matching the legacy encoder. ``active_names`` gives the
    display the set of enabled flag names to fold into an ImGui mask without this
    module importing ImGui.
    """

    no_move: bool = False
    no_resize: bool = False
    no_collapse: bool = False
    no_title_bar: bool = False
    no_scrollbar: bool = False
    auto_resize: bool = False

    _WIRE_KEYS: ClassVar[tuple[str, ...]] = (
        "no_move",
        "no_resize",
        "no_collapse",
        "no_title_bar",
        "no_scrollbar",
        "auto_resize",
    )

    @classmethod
    def from_wire(cls, d: Mapping[str, object]) -> WindowFlags:
        """Read the boolean flags from a wire dict, each defaulting to False."""
        values = {
            key: PatchField(key).as_bool(d.get(key, False)) for key in cls._WIRE_KEYS
        }
        return cls(**values)

    def to_wire(self) -> dict[str, object]:
        """Return only the flags that are set — an off flag is omitted."""
        return {key: True for key in self._WIRE_KEYS if getattr(self, key)}

    def active_names(self) -> tuple[str, ...]:
        """Return the names of the flags that are enabled, in wire order."""
        return tuple(key for key in self._WIRE_KEYS if getattr(self, key))
