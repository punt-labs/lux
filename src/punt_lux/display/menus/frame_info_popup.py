"""FrameInfoPopup and FrameInfoButton — the title-bar info affordance: a
glyph on each frame's title bar, and the popup it opens.

The button and the popup are the two collaborating halves of one affordance
(the button computes where to anchor the popup; the popup owns what shows
once opened), so they share this module rather than each earning its own
file (PY-OO-2: a class and its close collaborator, not an unrelated pair).

``FrameInfoPopup`` renders in ImGui's dedicated popup layer -- always above
every normal and docked window by construction -- so a popup spawned from a
frame's own title-bar glyph sits above that frame rather than behind it. A
plain floating window cannot: the click that opens the popup focuses the
frame it lands in, and a same-click same-frame focus outranks a floating
window. One popup at a time, anchored at the glyph, dismissed by ImGui itself
on an outside click. Its rows are a plain snapshot the Hub already formatted
(``FrameOwnerFacts``, DES-c7xi's Hub->display replication), so rendering is
render-loop-cheap: no live read, no per-frame lookup, just the last cached
snapshot for whichever frame is currently open.

Both classes address a frame by ``(hub, frame_id)``, never a bare id: two
Hubs can mint the identical frame id, and ``FrameBook``/``HubScopedStore``
already resolve every other frame lookup that way (DES-c7xi round 3).

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from imgui_bundle import ImVec2

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.identity import HubId

__all__ = ["FrameInfoButton", "FrameInfoPopup"]

# What the popup shows when the Hub has no facts for the frame's owner yet --
# untracked or the owning connection has already departed. Distinguished from
# a resolved-but-genuinely-empty result so a click is never a silent no-op.
_UNKNOWN_OWNER_ROWS: tuple[tuple[str, str], ...] = (("Owner", "unknown"),)


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

    _frame_for: Callable[[str, HubId], Frame | None]
    _open_frame_id: str | None
    _open_hub: HubId | None
    _rows: tuple[tuple[str, str], ...]
    _spawn_pos: tuple[float, float]
    _placed: bool
    __slots__ = (
        "_frame_for",
        "_open_frame_id",
        "_open_hub",
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

    def close(self) -> None:
        """Close the popup, if open. A no-op otherwise."""
        self._open_frame_id = None
        self._open_hub = None

    def render(self, imgui: Any) -> None:
        """Render the popup in ImGui's always-on-top popup layer while open.

        Auto-closes if its frame is gone, and syncs to ImGui's own dismissal
        (an outside click or Escape) the frame ``begin_popup`` reports the
        popup shut. ``end_popup`` balances only a ``begin_popup`` that opened.
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
            self._render_rows(imgui)
        finally:
            imgui.end_popup()

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

        ``open_popup`` and ``begin_popup`` (in ``render``) must fire at the
        same ID-stack scope for ImGui to match them; both live here at the
        render loop's root scope, never in the title-bar button's frame scope.
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


@final
class FrameInfoButton:
    """The title-bar info glyph, positioned just left of the native close x.

    Clicking it opens the :class:`FrameInfoPopup` it was built to drive,
    anchored at the glyph, showing the frame's owning-connection facts the
    Hub attached to its last push. Facts are read from ``facts_for`` by
    ``(hub, frame_id)``, not from the frame itself -- the snapshot lives in
    the :class:`~punt_lux.display.replica.owner_facts_cache.OwnerFactsStore`
    ``SceneReplica`` owns, not on the ``Frame`` aggregate root.

    Painted on the foreground draw list rather than as a normal ImGui item:
    a title bar sits outside the window's content-area clip rect, so an item
    placed there (``small_button`` included) is silently culled by ImGui's
    own visibility check before it ever draws -- no error, just nothing on
    screen and no click ever reaches it. The foreground draw list has no
    such clip rect (mirrors ``DockPill``'s identical rationale), so this
    paints the glyph by hand and hit-tests the raw mouse position instead of
    relying on an ImGui item to claim the click.
    """

    # ASCII "i": primary font + fallback lack U+24D8 "ⓘ", which renders as tofu.
    _LABEL = "i"
    _GAP = 4.0
    _SCALE = 0.625  # glyph diameter as a fraction of the title-bar band

    _popup: FrameInfoPopup
    _facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None]
    __slots__ = ("_facts_for", "_popup")

    def __new__(
        cls,
        popup: FrameInfoPopup,
        facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None],
    ) -> Self:
        self = super().__new__(cls)
        self._popup = popup
        self._facts_for = facts_for
        return self

    def render(self, frame: Frame, imgui: Any) -> None:
        """Draw the glyph for ``frame``; a click opens its info popup."""
        pos = imgui.get_window_pos()
        size = imgui.get_window_size()
        glyph = (band := imgui.get_frame_height()) * self._SCALE
        high = ImVec2(pos.x + size.x - band - self._GAP, pos.y + (band + glyph) / 2)
        low = ImVec2(high.x - glyph, high.y - glyph)
        hovered = self._paint(imgui, low, high)
        if hovered and imgui.is_mouse_clicked(imgui.MouseButton_.left):
            resolved = self._facts_for(frame.frame_id, frame.hub)
            rows = resolved if resolved is not None else _UNKNOWN_OWNER_ROWS
            self._popup.open_for(frame.frame_id, frame.hub, rows, (low.x, low.y))

    @staticmethod
    def _hovered(imgui: Any, low: ImVec2, high: ImVec2) -> bool:
        """Whether the mouse sits inside the glyph's rect -- a raw geometry
        check, since the glyph is not a real ImGui item for ImGui to hover."""
        mouse = imgui.get_mouse_pos()
        return bool(low.x <= mouse.x <= high.x and low.y <= mouse.y <= high.y)

    def _paint(self, imgui: Any, low: ImVec2, high: ImVec2) -> bool:
        """Fill the glyph's rect and center its label; return whether hovered.

        Reports its own hover state the way an ImGui widget returns its
        interaction result, so the caller reads it once for the click test
        rather than hit-testing the glyph a second time.
        """
        hovered = self._hovered(imgui, low, high)
        draw = imgui.get_foreground_draw_list()
        style = imgui.get_style()
        fill = imgui.Col_.button_hovered if hovered else imgui.Col_.button
        rounding = (high.x - low.x) * 0.5
        draw.add_rect_filled(
            low, high, imgui.get_color_u32(style.color_(fill)), rounding
        )
        text_size = imgui.calc_text_size(self._LABEL)
        text_pos = ImVec2(
            low.x + (high.x - low.x - text_size.x) * 0.5,
            low.y + (high.y - low.y - text_size.y) * 0.5,
        )
        draw.add_text(
            text_pos, imgui.get_color_u32(style.color_(imgui.Col_.text)), self._LABEL
        )
        return hovered
