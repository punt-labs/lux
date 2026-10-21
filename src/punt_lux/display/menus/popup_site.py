"""PopupSite — which frame the info popup is open for, what it shows, and where.

The popup's state, apart from the ImGui calls that draw it: the open frame
(addressed by Hub as well as id), the panel of rows, the anchor, and a pending
close request.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.connection_panel import ConnectionPanel

if TYPE_CHECKING:
    from punt_lux.domain.identity import HubId

__all__ = ["OpenFrame", "PopupSite"]


@dataclass(frozen=True, slots=True)
class OpenFrame:
    """A frame addressed by its Hub as well as its id: two Hubs can mint one id."""

    frame_id: str
    hub: HubId

    def __str__(self) -> str:
        return f"hub={self.hub} frame={self.frame_id}"


@final
class PopupSite:
    """The state of the one info popup: closed, or open for exactly one frame."""

    # None is the closed state.
    _open: OpenFrame | None
    _panel: ConnectionPanel
    _pos: tuple[float, float]
    _placed: bool
    _close_requested: bool
    __slots__ = ("_close_requested", "_open", "_panel", "_placed", "_pos")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._open = None
        self._panel = ConnectionPanel(())
        self._pos = (0.0, 0.0)
        self._placed = True
        self._close_requested = False
        return self

    @property
    def frame(self) -> OpenFrame | None:
        """The frame the popup is open for, or ``None`` while it is closed."""
        return self._open

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        """The label/value rows the popup shows."""
        return self._panel.rows

    @property
    def pos(self) -> tuple[float, float]:
        """The anchor the popup will place itself at on its next render."""
        return self._pos

    @property
    def is_close_requested(self) -> bool:
        """Whether a dismissal is waiting for the next render to carry out."""
        return self._close_requested

    def open(
        self,
        frame: OpenFrame,
        rows: tuple[tuple[str, str], ...],
        pos: tuple[float, float],
    ) -> None:
        """Open (or replace) the popup for ``frame`` at ``pos``."""
        self._open = frame
        self._panel = ConnectionPanel(rows)
        self._pos = pos
        self._placed = False
        self._close_requested = False

    def replace_rows(self, rows: tuple[tuple[str, str], ...]) -> None:
        """Show ``rows`` instead, so facts replicated after opening appear."""
        if rows != self._panel.rows:
            self._panel = ConnectionPanel(rows)

    def request_close(self) -> None:
        """Ask the next render to dismiss the popup."""
        self._close_requested = True

    def close(self) -> None:
        """Close the popup, if open. A no-op otherwise."""
        self._open = None
        self._close_requested = False

    def place(self, imgui: Any, popup_id: str) -> None:
        """Open ``popup_id`` in the popup layer at the anchor, once per opening.

        ``open_popup`` and ``begin_popup`` must fire at the same ID-stack scope
        for ImGui to match them; the caller begins at the render loop's root.
        """
        if self._placed:
            return
        imgui.open_popup(popup_id)
        imgui.set_next_window_pos(self._pos, imgui.Cond_.always.value)
        self._placed = True

    def draw(self, imgui: Any) -> bool:
        """Draw the panel; return whether its close button was pressed."""
        return self._panel.render(imgui)

    @staticmethod
    def flags(imgui: Any) -> int:
        """Return the window flags: no collapse arrow, sized to its contents."""
        flags = imgui.WindowFlags_
        return int(flags.no_collapse.value | flags.always_auto_resize.value)
