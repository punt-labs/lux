"""FrameInfoPopup — the title-bar info glyph's popup, opened by open_for().

Renders in ImGui's dedicated popup layer -- always above every normal and
docked window by construction -- so a popup spawned from a frame's own
title-bar glyph sits above that frame rather than behind it. One popup at a
time, anchored at the glyph. Two gestures dismiss it, both routed through
ImGui's own ``close_current_popup`` so the popup and this object's state shut
together: the header's close button, and a second click on the title-bar glyph
(:class:`~punt_lux.display.menus.frame_info_button.FrameInfoButton` calls
:meth:`request_close`). Its rows are a plain snapshot the Hub already formatted
(``FrameOwnerFacts``, replicated Hub->display), so rendering is render-loop-cheap.

Addressed by ``(hub, frame_id)``, never a bare id: two Hubs can mint the
identical frame id.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.popup_site import OpenFrame, PopupSite

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.identity import HubId

__all__ = ["FrameInfoPopup"]

logger = logging.getLogger(__name__)


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
    _site: PopupSite
    __slots__ = ("_frame_for", "_site")

    def __new__(cls, frame_for: Callable[[str, HubId], Frame | None]) -> Self:
        self = super().__new__(cls)
        self._frame_for = frame_for
        self._site = PopupSite()
        return self

    @property
    def is_open(self) -> bool:
        """Return whether the popup is currently showing."""
        return self._site.frame is not None

    @property
    def spawn_pos(self) -> tuple[float, float]:
        """The anchor the popup will place itself at on its next render."""
        return self._site.pos

    @property
    def open_frame(self) -> OpenFrame | None:
        """The frame the popup is open for, or ``None`` while it is closed."""
        return self._site.frame

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        """The label/value rows the popup will render."""
        return self._site.rows

    def is_open_for(self, frame_id: str, hub: HubId) -> bool:
        """Return whether the popup is open for exactly ``(hub, frame_id)``."""
        return self._site.frame == OpenFrame(frame_id, hub)

    def open_for(
        self,
        frame_id: str,
        hub: HubId,
        rows: tuple[tuple[str, str], ...],
        anchor: tuple[float, float],
    ) -> None:
        """Open (or replace) the popup for ``(hub, frame_id)`` at ``anchor``."""
        self._site.open(OpenFrame(frame_id, hub), rows, anchor)

    def replace_rows(self, rows: tuple[tuple[str, str], ...]) -> None:
        """Show ``rows`` instead, so facts replicated after opening appear."""
        self._site.replace_rows(rows)

    def request_close(self) -> None:
        """Ask the next render to dismiss the popup through ImGui.

        The glyph that opened the popup calls this on a second click; the close
        runs on the next ``render`` via ``close_current_popup`` so ImGui's popup
        stack and this object's state shut in the same step.
        """
        self._site.request_close()

    def close(self) -> None:
        """Close the popup, if open. A no-op otherwise."""
        self._site.close()

    def render(self, imgui: Any) -> None:
        """Render the popup in ImGui's always-on-top popup layer while open.

        Auto-closes if its frame is gone, and syncs to ImGui's own dismissal
        (outside click/Escape) that ``begin_popup`` reports shut. ``end_popup``
        balances only a ``begin_popup`` that opened.
        """
        frame = self._site.frame
        if frame is None:
            return
        if self._frame_for(frame.frame_id, frame.hub) is None:
            self._close_because("its frame is gone")
            return
        self._site.place(imgui, self._POPUP_ID)
        if not imgui.begin_popup(self._POPUP_ID, self._site.flags(imgui)):
            self._close_because("dismissed by imgui")
            return
        try:
            self._render_body(imgui)
        finally:
            imgui.end_popup()

    def _close_because(self, reason: str) -> None:
        """Log why the popup shut, then close it.

        Neither a vanished frame nor ImGui's own dismissal (outside click,
        Escape, a focus change over the window it opened from) reports itself,
        and a popup that vanishes without a trace is undiagnosable. Closing
        clears the open state, so each shutting logs exactly once.
        """
        logger.info("frame-info popup for %s closed: %s", self._site.frame, reason)
        self._site.close()

    def _render_body(self, imgui: Any) -> None:
        """Dismiss on a pending close, else draw the header and the rows.

        Both dismiss gestures land on a close request -- the header's close
        button and the glyph's :meth:`request_close` -- and this one place turns
        that into ``close_current_popup``, so ImGui's popup stack and this
        object's state always shut together on the next ``begin_popup``.
        """
        if self._site.is_close_requested:
            imgui.close_current_popup()
            self._site.close()
            return
        if self._site.draw(imgui):
            self._site.request_close()
