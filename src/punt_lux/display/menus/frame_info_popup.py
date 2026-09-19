"""FrameInfoPopup and FrameInfoButton — the title-bar info affordance: a
glyph on each frame's title bar, and the popup it opens.

The button and the popup are the two collaborating halves of one affordance
(the button computes where to anchor the popup; the popup owns what shows
once opened), so they share this module rather than each earning its own
file (PY-OO-2: a class and its close collaborator, not an unrelated pair).

``FrameInfoPopup`` is modeled on
:class:`~punt_lux.display.menus.projections.WorldPanel`: a small,
self-managed floating window, one at a time, placed at the click that opened
it and dismissed on a click elsewhere. Unlike the World panel it renders no
menu model — its rows are a plain snapshot the Hub already formatted
(``FrameOwnerFacts``, DES-c7xi's Hub->display replication), so rendering is
render-loop-cheap: no live read, no per-frame lookup, just the last cached
snapshot for whichever frame is currently open.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.display.replica.frame import Frame

__all__ = ["FrameInfoButton", "FrameInfoPopup"]


@final
class FrameInfoPopup:
    """Show one frame's owning-connection facts, opened by its title-bar glyph.

    One popup at a time: opening a different frame's glyph replaces whichever
    was open, rather than stacking a second window.
    """

    _get_frames: Callable[[], Mapping[str, Frame]]
    _open_frame_id: str | None
    _rows: tuple[tuple[str, str], ...]
    _spawn_pos: tuple[float, float]
    _placed: bool
    __slots__ = (
        "_get_frames",
        "_open_frame_id",
        "_placed",
        "_rows",
        "_spawn_pos",
    )

    def __new__(cls, get_frames: Callable[[], Mapping[str, Frame]]) -> Self:
        self = super().__new__(cls)
        self._get_frames = get_frames
        self._open_frame_id = None
        self._rows = ()
        self._spawn_pos = (0.0, 0.0)
        self._placed = True
        return self

    @property
    def is_open(self) -> bool:
        """Return whether the popup is currently showing."""
        return self._open_frame_id is not None

    def open_for(
        self,
        frame_id: str,
        rows: tuple[tuple[str, str], ...],
        anchor: tuple[float, float],
    ) -> None:
        """Open (or replace) the popup for ``frame_id``, anchored at ``anchor``."""
        self._open_frame_id = frame_id
        self._rows = rows
        self._spawn_pos = anchor
        self._placed = False

    def close(self) -> None:
        """Close the popup, if open. A no-op otherwise."""
        self._open_frame_id = None

    def check_background_click(self, imgui: Any) -> None:
        """Dismiss the popup on a left click that lands on the workspace background.

        Mirrors ``WorldPanel.check_background_click``'s detection, called at
        the same point in the render loop -- before any frame or the popup
        itself paints this frame, so "the current window" here is still the
        background dockspace.
        """
        if self._open_frame_id is None:
            return
        if not imgui.is_mouse_clicked(imgui.MouseButton_.left):
            return
        if imgui.is_any_item_hovered():
            return
        if not imgui.is_window_hovered():
            return
        self.close()

    def render(self, imgui: Any) -> None:
        """Render the popup while open; auto-closes if its frame is gone."""
        if self._open_frame_id is None:
            return
        if self._open_frame_id not in self._get_frames():
            self.close()
            return
        self._place(imgui)
        wants_open = True  # ImGui writes the close-button's answer back into this
        _, still_open = imgui.begin(
            "Connection###frame_info_popup", wants_open, self._flags(imgui)
        )
        try:
            if not still_open:
                self.close()
                return
            self._render_rows(imgui)
        finally:
            imgui.end()  # a raising action must not leave the window stack unbalanced

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
        """Put the popup where the glyph was clicked, the first frame only."""
        if self._placed:
            return
        imgui.set_next_window_pos(self._spawn_pos, imgui.Cond_.always.value)
        self._placed = True

    @staticmethod
    def _flags(imgui: Any) -> int:
        """Return the window flags: no collapse arrow, sized to its contents."""
        flags = imgui.WindowFlags_
        return int(flags.no_collapse.value | flags.always_auto_resize.value)


@final
class FrameInfoButton:
    """The title-bar info glyph, positioned just left of the native close x.

    Clicking it opens the :class:`FrameInfoPopup` it was built to drive,
    anchored at the glyph, showing the frame's owning-connection facts the
    Hub attached to its last push. Facts are read from ``facts_for`` by
    frame id, not from the frame itself -- the snapshot lives in the
    :class:`~punt_lux.display.replica.owner_facts_cache.OwnerFactsStore`
    ``SceneReplica`` owns, not on the ``Frame`` aggregate root.
    """

    # ASCII "i" -- the primary font and its merged fallback do not cover
    # U+24D8 "ⓘ", which would render as tofu.
    _LABEL = "i"
    _GAP = 4.0

    _popup: FrameInfoPopup
    _facts_for: Callable[[str], tuple[tuple[str, str], ...] | None]
    __slots__ = ("_facts_for", "_popup")

    def __new__(
        cls,
        popup: FrameInfoPopup,
        facts_for: Callable[[str], tuple[tuple[str, str], ...] | None],
    ) -> Self:
        self = super().__new__(cls)
        self._popup = popup
        self._facts_for = facts_for
        return self

    def render(self, frame: Frame, imgui: Any) -> None:
        """Draw the glyph for ``frame``; a click opens its info popup."""
        pos = imgui.get_window_pos()
        button_size = imgui.get_frame_height()
        x = pos.x + imgui.get_window_size().x - 2 * button_size - self._GAP
        imgui.set_cursor_screen_pos((x, pos.y))
        if imgui.small_button(f"{self._LABEL}##frame_info_{frame.frame_id}"):
            anchor = imgui.get_item_rect_min()
            rows = self._facts_for(frame.frame_id) or ()
            self._popup.open_for(frame.frame_id, rows, (anchor.x, anchor.y))
