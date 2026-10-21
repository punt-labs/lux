"""PopupSite — whether the info popup is open, and the ImGui calls that place it.

Closed is ``None`` and nothing else: closing drops the whole ``OpenPopup``, so no
remnant of a shut popup can be read back. Asking a closed site for what an open
popup owns (rows, anchor, a pending close) raises ``ValueError``.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import Any, Self, final

from punt_lux.display.menus.open_popup import OpenFrame, OpenPopup

__all__ = ["PopupSite"]


@final
class PopupSite:
    """The state of the one info popup: closed, or open for exactly one frame."""

    # None is the closed state.
    _open: OpenPopup | None
    __slots__ = ("_open",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._open = None
        return self

    @property
    def is_open(self) -> bool:
        """Whether the popup is open."""
        return self._open is not None

    @property
    def frame(self) -> OpenFrame | None:
        """The frame the popup is open for, or ``None`` while it is closed."""
        return self._open.frame if self._open else None

    @property
    def window_id(self) -> int | None:
        """The ImGui id of the open popup's window; ``None`` before it is placed."""
        return self._open.window_id if self._open else None

    @property
    def rows(self) -> tuple[tuple[str, str], ...]:
        """The label/value rows the open popup shows."""
        return self._require_open().panel.rows

    @property
    def pos(self) -> tuple[float, float]:
        """The anchor the open popup places itself at."""
        return self._require_open().pos

    @property
    def is_close_requested(self) -> bool:
        """Whether a dismissal is waiting for the next render to carry out."""
        return self._require_open().is_close_requested

    def open(
        self,
        frame: OpenFrame,
        rows: tuple[tuple[str, str], ...],
        pos: tuple[float, float],
    ) -> None:
        """Open (or replace) the popup for ``frame`` at ``pos``."""
        self._open = OpenPopup.opened(frame, rows, pos)

    def replace_rows(self, rows: tuple[tuple[str, str], ...]) -> None:
        """Show ``rows`` instead, so facts replicated after opening appear."""
        self._open = self._require_open().with_rows(rows)

    def request_close(self) -> None:
        """Ask the next render to dismiss the open popup."""
        self._open = self._require_open().close_requested()

    def close(self) -> None:
        """Close the popup, dropping all of its state. A no-op if closed."""
        self._open = None

    def place(self, imgui: Any, popup_id: str) -> None:
        """Open ``popup_id`` in the popup layer at the anchor, once per opening."""
        self._open = self._require_open().placed_in(imgui, popup_id)

    def draw(self, imgui: Any) -> bool:
        """Draw the panel; return whether its close button was pressed."""
        return self._require_open().panel.render(imgui)

    @staticmethod
    def flags(imgui: Any) -> int:
        """Return the window flags: no collapse arrow, sized to its contents."""
        flags = imgui.WindowFlags_
        return int(flags.no_collapse.value | flags.always_auto_resize.value)

    def _require_open(self) -> OpenPopup:
        """Return the open popup, or raise ``ValueError`` if it is closed."""
        if self._open is None:
            msg = "the info popup is closed"
            raise ValueError(msg)
        return self._open
