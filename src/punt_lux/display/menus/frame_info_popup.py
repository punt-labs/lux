"""FrameInfoPopup — the title-bar info glyph's popup, opened by open_for().

Renders in ImGui's dedicated popup layer -- always above every normal and
docked window by construction -- so a popup spawned from a frame's own
title-bar glyph sits above that frame rather than behind it. One popup at a
time, anchored at the glyph. Two gestures dismiss it, both routed through
ImGui's own ``close_current_popup`` so the popup and this object's state shut
together: the header's close button, and a second click on the title-bar glyph
(:class:`~punt_lux.display.menus.frame_info_button.FrameInfoButton` calls
:meth:`request_close`). Its rows are a plain snapshot the Hub already formatted
(``FrameOwnerFacts``, DES-c7xi's Hub->display replication), so rendering is
render-loop-cheap.

Addressed by ``(hub, frame_id)``, never a bare id: two Hubs can mint the
identical frame id (DES-c7xi round 3).

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.identity import HubId

__all__ = ["FrameInfoPopup"]


@final
class FrameInfoPopup:
    """Show one frame's owning-connection facts, opened by its title-bar glyph.

    One popup at a time: opening a different frame's glyph replaces whichever
    was open, rather than stacking a second window.
    """

    # A stable, title-independent popup-stack id. ImGui keys the popup-layer
    # entry off this, so the popup never re-hashes and self-dismisses when its
    # rows change, and one id enforces the one-at-a-time rule for free.
    _POPUP_ID = "frame_info_popup"

    # The header title and the ASCII close-button label. "x" stands in for
    # U+2715, which renders as tofu (as the title-bar glyph is ASCII "i").
    _TITLE = "Connection"
    _CLOSE_LABEL = "x"

    _frame_for: Callable[[str, HubId], Frame | None]
    _open_frame_id: str | None
    _open_hub: HubId | None
    _rows: tuple[tuple[str, str], ...]
    _spawn_pos: tuple[float, float]
    _placed: bool
    _pending_close: bool
    __slots__ = (
        "_frame_for",
        "_open_frame_id",
        "_open_hub",
        "_pending_close",
        "_placed",
        "_rows",
        "_spawn_pos",
    )

    def __new__(cls, frame_for: Callable[[str, HubId], Frame | None]) -> Self:
        self = super().__new__(cls)
        self._frame_for = frame_for
        self._open_frame_id = None
        self._open_hub = None
        self._rows = ()
        self._spawn_pos = (0.0, 0.0)
        self._placed = True
        self._pending_close = False
        return self

    @property
    def is_open(self) -> bool:
        """Return whether the popup is currently showing."""
        return self._open_frame_id is not None

    @property
    def spawn_pos(self) -> tuple[float, float]:
        """The anchor the popup will place itself at on its next render."""
        return self._spawn_pos

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        """The label/value rows the popup will render."""
        return self._rows

    def is_open_for(self, frame_id: str, hub: HubId) -> bool:
        """Return whether the popup is open for exactly ``(hub, frame_id)``."""
        return self._open_frame_id == frame_id and self._open_hub == hub

    def open_for(
        self,
        frame_id: str,
        hub: HubId,
        rows: tuple[tuple[str, str], ...],
        anchor: tuple[float, float],
    ) -> None:
        """Open (or replace) the popup for ``(hub, frame_id)`` at ``anchor``."""
        self._open_frame_id = frame_id
        self._open_hub = hub
        self._rows = rows
        self._spawn_pos = anchor
        self._placed = False
        self._pending_close = False

    def request_close(self) -> None:
        """Ask the next render to dismiss the popup through ImGui.

        The glyph that opened the popup calls this on a second click; the close
        runs on the next ``render`` via ``close_current_popup`` so ImGui's popup
        stack and this object's state shut in the same step.
        """
        self._pending_close = True

    def close(self) -> None:
        """Close the popup, if open. A no-op otherwise."""
        self._open_frame_id = None
        self._open_hub = None
        self._pending_close = False

    def render(self, imgui: Any) -> None:
        """Render the popup in ImGui's always-on-top popup layer while open.

        Auto-closes if its frame is gone, and syncs to ImGui's own dismissal
        (outside click/Escape) that ``begin_popup`` reports shut. ``end_popup``
        balances only a ``begin_popup`` that opened.
        """
        if self._open_frame_id is None or self._open_hub is None:
            return
        if self._frame_for(self._open_frame_id, self._open_hub) is None:
            self.close()
            return
        self._place(imgui)
        if not imgui.begin_popup(self._POPUP_ID, self._flags(imgui)):
            self.close()
            return
        try:
            self._render_body(imgui)
        finally:
            imgui.end_popup()

    def _render_body(self, imgui: Any) -> None:
        """Dismiss on a pending close, else draw the header and the rows.

        Both dismiss gestures land on ``_pending_close`` -- the header's close
        button and the glyph's :meth:`request_close` -- and this one place turns
        that into ``close_current_popup``, so ImGui's popup stack and this
        object's state always shut together on the next ``begin_popup``.
        """
        if self._pending_close:
            imgui.close_current_popup()
            self.close()
            return
        self._render_header(imgui)
        self._render_rows(imgui)

    def _render_header(self, imgui: Any) -> None:
        """Draw the title and a right-aligned close button, above a rule.

        The close button arms ``_pending_close`` rather than dismissing inline,
        so it shares the one dismissal path :meth:`_render_body` owns.
        """
        button_width = imgui.calc_text_size(self._CLOSE_LABEL).x
        button_width += imgui.get_style().frame_padding.x * 2.0
        imgui.text(self._TITLE)
        imgui.same_line(imgui.get_content_region_avail().x - button_width)
        if imgui.small_button(self._CLOSE_LABEL):
            self._pending_close = True
        imgui.separator()

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

    def _place(self, imgui: Any) -> None:
        """Open the popup in the popup layer and anchor it at the glyph, once.

        ``open_popup`` and ``begin_popup`` must fire at the same ID-stack scope
        for ImGui to match them; both live here at the render loop's root scope.
        """
        if self._placed:
            return
        imgui.open_popup(self._POPUP_ID)
        imgui.set_next_window_pos(self._spawn_pos, imgui.Cond_.always.value)
        self._placed = True

    @staticmethod
    def _flags(imgui: Any) -> int:
        """Return the window flags: no collapse arrow, sized to its contents."""
        flags = imgui.WindowFlags_
        return int(flags.no_collapse.value | flags.always_auto_resize.value)
