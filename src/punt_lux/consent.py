"""ImGui consent dialog for code-on-demand.

Shows a modal with the source code and any AST warnings.
The user clicks Allow or Deny.  This is the security boundary —
the AST scanner is just a UX signal, the consent prompt is the gate.
"""

from __future__ import annotations

import time
from enum import Enum, auto
from typing import Any


class ConsentResult(Enum):
    """Result of the consent dialog."""

    PENDING = auto()
    ALLOWED = auto()
    DENIED = auto()


class ConsentDialog:
    """Manages an ImGui modal consent dialog for render function code.

    Usage::

        dialog = ConsentDialog(source, warnings)
        # In your render loop:
        result = dialog.draw()
        if result == ConsentResult.ALLOWED: ...
        if result == ConsentResult.DENIED: ...
    """

    MODAL_TITLE = "Agent wants to run custom code"

    def __init__(self, source: str, warnings: list[str] | None = None) -> None:
        self.source = source
        self.warnings = warnings or []
        self._result = ConsentResult.PENDING
        self._opened = False
        self.created_at = time.monotonic()

    @property
    def result(self) -> ConsentResult:
        """Current consent state."""
        return self._result

    def draw(self) -> ConsentResult:
        """Draw the consent dialog.  Call every frame while pending.

        Returns the current result (PENDING until the user clicks).
        """
        if self._result != ConsentResult.PENDING:
            return self._result

        from imgui_bundle import imgui

        # Open the modal on first draw
        if not self._opened:
            imgui.open_popup(self.MODAL_TITLE)
            self._opened = True

        # Center the modal
        viewport = imgui.get_main_viewport()
        center = viewport.get_center()
        imgui.set_next_window_pos(center, imgui.Cond_.appearing.value, (0.5, 0.5))
        imgui.set_next_window_size((700, 500), imgui.Cond_.appearing.value)

        opened, _ = imgui.begin_popup_modal(
            self.MODAL_TITLE, None, imgui.WindowFlags_.no_resize.value
        )
        if not opened:
            return self._result

        try:
            self._draw_content(imgui)
        finally:
            imgui.end_popup()

        return self._result

    def _draw_content(self, imgui: Any) -> None:
        """Render the modal body: header, warnings, code, buttons."""
        # Header
        imgui.text_wrapped(
            "The following Python code wants to run in the render loop. "
            "Review it carefully before allowing."
        )
        imgui.spacing()

        # Warnings (if any)
        if self.warnings:
            imgui.push_style_color(imgui.Col_.text.value, (1.0, 0.85, 0.0, 1.0))
            imgui.text("Warnings:")
            for w in self.warnings:
                imgui.bullet_text(w)
            imgui.pop_style_color()
            imgui.spacing()
            imgui.separator()
            imgui.spacing()

        # Source code in a scrollable child region
        imgui.text("Source code:")
        avail = imgui.get_content_region_avail()
        code_height = avail.y - 50  # room for buttons

        imgui.push_style_color(imgui.Col_.child_bg.value, (0.1, 0.1, 0.12, 1.0))
        if imgui.begin_child(
            "code_view", (0, code_height), child_flags=imgui.ChildFlags_.borders.value
        ):
            try:
                for i, line in enumerate(self.source.split("\n"), 1):
                    imgui.push_style_color(imgui.Col_.text.value, (0.5, 0.5, 0.5, 1.0))
                    imgui.text(f"{i:4d} ")
                    imgui.pop_style_color()
                    imgui.same_line()
                    imgui.push_style_color(imgui.Col_.text.value, (0.7, 0.9, 0.7, 1.0))
                    imgui.text(line)
                    imgui.pop_style_color()
            finally:
                imgui.end_child()
        imgui.pop_style_color()

        imgui.spacing()
        self._draw_buttons(imgui)

    def _draw_buttons(self, imgui: Any) -> None:
        """Render centered Allow / Deny buttons."""
        button_width = 120.0
        spacing = 20.0
        total = button_width * 2 + spacing
        imgui.set_cursor_pos_x((imgui.get_window_width() - total) / 2)

        imgui.push_style_color(imgui.Col_.button.value, (0.2, 0.6, 0.2, 1.0))
        imgui.push_style_color(imgui.Col_.button_hovered.value, (0.3, 0.7, 0.3, 1.0))
        if imgui.button("Allow", (button_width, 32)):
            self._result = ConsentResult.ALLOWED
            imgui.close_current_popup()
        imgui.pop_style_color(2)

        imgui.same_line(0, spacing)

        imgui.push_style_color(imgui.Col_.button.value, (0.6, 0.2, 0.2, 1.0))
        imgui.push_style_color(imgui.Col_.button_hovered.value, (0.7, 0.3, 0.3, 1.0))
        if imgui.button("Deny", (button_width, 32)):
            self._result = ConsentResult.DENIED
            imgui.close_current_popup()
        imgui.pop_style_color(2)
