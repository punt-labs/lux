"""ConnectionPanel — the frame-info popup's body: a titled header over fact rows.

A plain snapshot the Hub already formatted (``FrameOwnerFacts``, the Hub->display
replication), so drawing it is render-loop-cheap. It only draws; whether it is
shown, where, and when it shuts belongs to the popup that hosts it. The close
button follows the title at a fixed gap, never a right edge derived from the
width left over: the popup auto-sizes, so that would feed back into its width.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import Any, Self, final

__all__ = ["ConnectionPanel"]


@final
class ConnectionPanel:
    """One frame's owning-connection facts, drawn as a header and a 2-column grid."""

    # The header title and the ASCII close-button label. "x" stands in for
    # U+2715, which renders as tofu (as the title-bar glyph is ASCII "i").
    _TITLE = "Connection"
    _CLOSE_LABEL = "x"

    _rows: tuple[tuple[str, str], ...]
    __slots__ = ("_rows",)

    def __new__(cls, rows: tuple[tuple[str, str], ...]) -> Self:
        self = super().__new__(cls)
        self._rows = rows
        return self

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        """The label/value rows this panel draws."""
        return self._rows

    def render(self, imgui: Any) -> bool:
        """Draw the header and the rows; return whether close was pressed."""
        is_close_pressed = self._render_header(imgui)
        self._render_rows(imgui)
        return is_close_pressed

    def _render_header(self, imgui: Any) -> bool:
        """Draw the title and its close button on one line, above a rule."""
        imgui.text(self._TITLE)
        imgui.same_line(0.0, imgui.get_style().item_spacing.x * 2.0)
        is_close_pressed = bool(imgui.small_button(self._CLOSE_LABEL))
        imgui.separator()
        return is_close_pressed

    def _render_rows(self, imgui: Any) -> None:
        """Render the facts as a compact 2-column label/value grid."""
        if not imgui.begin_table("##frame_info_rows", 2):
            return
        try:
            for label, value in self._rows:
                imgui.table_next_row()
                imgui.table_next_column()
                imgui.text(label)
                imgui.table_next_column()
                imgui.text(value)
        finally:
            imgui.end_table()
