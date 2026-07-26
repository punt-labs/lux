# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiWindowRenderer — paint a WindowElement as a movable ImGui sub-window.

``begin`` seeds the window's initial position and size with ``first_use_ever`` —
so an agent's placement applies once and the user's drag and resize are
Display-local thereafter, never re-pushed — folds the disabled behaviours into a
window-flags mask, and opens the window. Deliberately no ``p_open`` is passed:
the element carries no close affordance, so ImGui draws no close button and the
window cannot be dismissed. The skeleton paints the children through the default
recursion; ``end`` closes the window (``imgui.begin`` is always paired with
``imgui.end``) and applies the hover tooltip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self, final

from imgui_bundle import imgui

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.window import WindowElement

__all__ = ["ImGuiWindowRenderer"]


@final
class ImGuiWindowRenderer:
    """Paint a ``WindowElement`` as a floating sub-window (begin/paint/end)."""

    _elem: WindowElement
    _factory: ImGuiRendererFactory

    # WindowFlags attr name -> ImGui ``WindowFlags_`` member. ``auto_resize`` is
    # the one rename (ImGui spells it ``always_auto_resize``); the rest map 1:1.
    _FLAG_MEMBERS: ClassVar[dict[str, str]] = {
        "no_move": "no_move",
        "no_resize": "no_resize",
        "no_collapse": "no_collapse",
        "no_title_bar": "no_title_bar",
        "no_scrollbar": "no_scrollbar",
        "auto_resize": "always_auto_resize",
    }

    def __new__(cls, elem: WindowElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Seed placement (first-use), open the window; return whether expanded.

        No ``p_open`` is passed, so the window has no close button — a window
        element is in-scene content, not a dismissable frame.
        """
        placement = self._elem.placement
        cond = imgui.Cond_.first_use_ever.value
        imgui.set_next_window_pos((placement.x, placement.y), cond)
        imgui.set_next_window_size((placement.width, placement.height), cond)
        title = self._elem.title or self._elem.id
        # Triple-hash pins the ImGui window identity to the element id alone: a
        # title change keeps the same window, so the user's drag/resize survives
        # instead of the window re-appearing at the first-use-ever placement.
        expanded, _ = imgui.begin(f"{title}###{self._elem.id}", flags=self._flag_mask())
        return expanded

    def _flag_mask(self) -> int:
        """Fold the window's enabled flags into an ImGui ``WindowFlags_`` mask."""
        mask = 0
        for name in self._elem.flags.active_names():
            mask |= getattr(imgui.WindowFlags_, self._FLAG_MEMBERS[name]).value
        return mask

    def paint(self) -> None:
        """Record the window's painted rect; its body is its children.

        Runs inside the open window, so the recorded rect reflects the user's
        drag and ImGui's auto-sizing — Display-local truth never re-pushed.
        """
        self._factory.geometry.record_window(self._elem.id)

    def end(self, *, opened: bool) -> None:
        """Close the window and apply the tooltip.

        ``imgui.begin`` is always paired with ``imgui.end`` regardless of the
        expanded/collapsed result, so ``end`` ignores ``opened``.
        """
        _ = opened
        imgui.end()
        self._factory.apply_tooltip(self._elem)
