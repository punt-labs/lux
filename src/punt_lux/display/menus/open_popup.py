"""OpenPopup — everything true of the info popup while it is open.

A popup that shuts is dropped whole, so none of this can be read back stale.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Self

from punt_lux.display.menus.connection_panel import ConnectionPanel

if TYPE_CHECKING:
    from punt_lux.domain.identity import HubId

__all__ = ["OpenFrame", "OpenPopup"]


@dataclass(frozen=True, slots=True)
class OpenFrame:
    """A frame addressed by its Hub as well as its id: two Hubs can mint one id."""

    frame_id: str
    hub: HubId

    def __str__(self) -> str:
        return f"hub={self.hub} frame={self.frame_id}"


@dataclass(frozen=True, slots=True)
class OpenPopup:
    """The popup's frame, panel, anchor, placement, and pending dismissal."""

    frame: OpenFrame
    panel: ConnectionPanel
    pos: tuple[float, float]
    is_placed: bool = False
    is_close_requested: bool = False

    @classmethod
    def opened(
        cls,
        frame: OpenFrame,
        rows: tuple[tuple[str, str], ...],
        pos: tuple[float, float],
    ) -> Self:
        """Return the state of a popup that has just opened, not yet placed."""
        return cls(frame, ConnectionPanel(rows), pos)

    def with_rows(self, rows: tuple[tuple[str, str], ...]) -> Self:
        """Return this popup showing ``rows``, or itself when they are unchanged."""
        if rows == self.panel.rows:
            return self
        return replace(self, panel=ConnectionPanel(rows))

    def close_requested(self) -> Self:
        """Return this popup with a dismissal waiting for the next render."""
        return replace(self, is_close_requested=True)

    def placed_in(self, imgui: Any, popup_id: str) -> Self:
        """Open ``popup_id`` in the popup layer at the anchor, once per opening.

        ``open_popup`` and ``begin_popup`` must fire at the same ID-stack scope
        for ImGui to match them; the caller begins at the render loop's root.
        Returns this popup, marked placed.
        """
        if self.is_placed:
            return self
        imgui.open_popup(popup_id)
        imgui.set_next_window_pos(self.pos, imgui.Cond_.always.value)
        return replace(self, is_placed=True)
