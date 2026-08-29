# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportMissingModuleSource=false
"""One minimized frame's pill: where it sits, whether it is under the mouse, and
what a click on it restores.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs. It is handed in
rather than imported so the pill paints into the caller's frame.

The pill is hit-tested against the raw mouse position rather than through an
``invisible_button``, because it is painted on the foreground draw list, which
has no window in the z-order for a widget to claim clicks from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from imgui_bundle import ImVec2

if TYPE_CHECKING:
    from punt_lux.display.replica import Frame, SceneReplica

__all__ = ["DockPill"]

_TEXT_PAD = 8.0
_ROUNDING = 4.0


@final
class DockPill:
    """A minimized frame drawn as a rounded button, sized to its own title."""

    _imgui: Any  # the caller's imgui module; imgui_bundle ships no type stubs
    _frame: Frame
    _low: ImVec2
    _high: ImVec2
    __slots__ = ("_frame", "_high", "_imgui", "_low")

    def __new__(cls, imgui: Any, frame: Frame, low: ImVec2, high: ImVec2) -> Self:
        self = super().__new__(cls)
        self._imgui = imgui
        self._frame = frame
        self._low = low
        self._high = high
        return self

    @classmethod
    def at(cls, imgui: Any, frame: Frame, anchor: ImVec2, height: float) -> Self:
        """The pill for *frame* with its top-left corner at *anchor*.

        Its width is its title's, so the bar cannot know where the next pill
        starts without building this one first — which is why overflow is
        decided against :attr:`right` rather than computed ahead of the layout.
        """
        width = imgui.calc_text_size(frame.title).x + _TEXT_PAD * 2.0
        return cls(imgui, frame, anchor, ImVec2(anchor.x + width, anchor.y + height))

    @property
    def right(self) -> float:
        """The x this pill ends at — where the next one may start."""
        return self._high.x

    def hovered(self) -> bool:
        """Whether the mouse is inside this pill."""
        mouse = self._imgui.get_mouse_pos()  # an untyped ImVec2: no stubs to read it
        return bool(
            self._low.x <= mouse.x <= self._high.x
            and self._low.y <= mouse.y <= self._high.y
        )

    def paint(self, draw: Any, *, hovered: bool) -> None:
        """Fill the pill in theme colours and write its title down the middle."""
        imgui = self._imgui
        style = imgui.get_style()
        fill = imgui.Col_.button_hovered if hovered else imgui.Col_.button
        draw.add_rect_filled(
            self._low, self._high, imgui.get_color_u32(style.color_(fill)), _ROUNDING
        )
        text = imgui.calc_text_size(self._frame.title)
        draw.add_text(
            ImVec2(self._low.x + _TEXT_PAD, self._middle(text.y)),
            imgui.get_color_u32(style.color_(imgui.Col_.text)),
            self._frame.title,
        )

    def restore(self, scenes: SceneReplica) -> None:
        """Take the frame out of the bar and bring it back to the front.

        A pill click is a user gesture like an applet's menu entry, so it goes
        through the same raise — restoring and focusing in one step.
        """
        scenes.raise_frame(self._frame.frame_id)

    def _middle(self, height: float) -> float:
        """The y that centres something *height* tall inside the pill."""
        return self._low.y + (self._high.y - self._low.y - height) * 0.5
