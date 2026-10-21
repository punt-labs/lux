"""PopupCover — how the info popup stands over one frame's glyph.

The popup opens at its glyph, so a second click lands on the popup and must
still reach that glyph. That allowance is narrow: it is this popup, and only
for the frame it is open for. Any other popup, or this one over another frame's
glyph, is a window in front of that glyph like any other.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["PopupCover"]


@dataclass(frozen=True, slots=True)
class PopupCover:
    """The info popup's window, and whether it is open for the glyph's own frame."""

    # None while no info popup has been placed: ImGui names its window at open.
    window_id: int | None
    is_for_frame: bool

    def is_under_mouse(self, imgui: Any) -> bool:
        """Whether the window under the mouse is this popup, open for the frame."""
        under = imgui.get_current_context().hovered_window
        # pybind yields None when no window is hovered, though the stub says Window.
        return bool(
            self.is_for_frame
            and self.window_id is not None
            and under
            and under.popup_id == self.window_id
        )

    def is_focused(self, imgui: Any) -> bool:
        """Whether ImGui's focused window belongs to this popup, for any frame.

        ImGui hides every other window from hover while a popup has focus; that
        is only to be looked through when the focused popup is this one.
        """
        focused = imgui.get_current_context().nav_window
        return bool(
            self.window_id is not None
            and focused
            and focused.root_window.popup_id == self.window_id
        )
