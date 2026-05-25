"""ImGuiDialogRenderer — paint a DialogElement as an ImGui modal popup.

``render()`` opens the popup if the model is visible, walks the dialog's
child Buttons through an injected ``ButtonRenderer``, then closes the
popup.

Visibility is sourced from the dialog's own ``DialogModel`` so the
single state machine — agent ``RemoveElement``, model dismiss,
connection disconnect — drives renderer behaviour without a detached
``open`` flag. Widget-state latches let the dismissed-by-renderer case
re-open once the model becomes visible again.

Child dispatch is Button-only (the only valid dialog child kind on the
wire today). Richer composite children extend the dispatch here rather
than going through ``ElementRenderer``, which keeps the dialog renderer
self-contained.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.button import ButtonElement

if TYPE_CHECKING:
    from punt_lux.display.renderers.button_renderer import ButtonRenderer
    from punt_lux.protocol.elements.dialog import DialogElement
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["ImGuiDialogRenderer"]


class ImGuiDialogRenderer:
    """Paint a ``DialogElement`` as an ImGui modal popup with children."""

    _elem: DialogElement
    _widget_state: WidgetState
    _button_renderer: ButtonRenderer

    # Widget-state latch values — keying matches the legacy
    # ``ElementRenderer._render_modal`` flow so a scene that previously
    # opened a modal under the same id keeps its dismiss state.
    _OPEN_KEY_SUFFIX: ClassVar[str] = "__open"
    _DISMISS_KEY_SUFFIX: ClassVar[str] = "__dismissed"
    _OPEN: ClassVar[int] = 1
    _CLOSED: ClassVar[int] = 0

    def __new__(
        cls,
        elem: DialogElement,
        widget_state: WidgetState,
        button_renderer: ButtonRenderer,
    ) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._widget_state = widget_state
        self._button_renderer = button_renderer
        return self

    def render(self) -> None:
        """Paint the dialog frame and recurse into its child Buttons."""
        eid = self._elem.id
        title = self._elem.title or eid
        popup_id = f"{title}##{eid}"
        open_key = f"{eid}{self._OPEN_KEY_SUFFIX}"
        dismiss_key = f"{eid}{self._DISMISS_KEY_SUFFIX}"

        was_open = self._widget_state.ensure(open_key, self._CLOSED) == self._OPEN
        dismissed = self._widget_state.ensure(dismiss_key, self._CLOSED) == self._OPEN

        if not self._elem.visible:
            if was_open or dismissed:
                self._widget_state.set(open_key, self._CLOSED)
                self._widget_state.set(dismiss_key, self._CLOSED)
            return

        if not was_open and not dismissed:
            imgui.open_popup(popup_id)
            self._widget_state.set(open_key, self._OPEN)
            was_open = True

        # Default p_open=None hides the close-X — the dialog dismisses
        # through the DialogModel via child Button handlers, not through
        # the popup chrome. The post-popup branch catches any user-driven
        # close (Esc, click-outside) and syncs both latch and model.
        visible, _p_open = imgui.begin_popup_modal(popup_id)
        if visible:
            for child in self._elem.children:
                self._render_child(child)
            imgui.end_popup()

        if was_open and not visible:
            self._handle_external_close(open_key, dismiss_key)

    def _handle_external_close(self, open_key: str, dismiss_key: str) -> None:
        """Sync widget-state latches and model after an ImGui-driven close.

        ImGui closes the popup itself when the user presses Escape or
        clicks outside. Pressing Escape on a modal IS a dismiss action;
        the model's ``close()`` triggers its observer cascade
        (``mark_removed`` → parent composites) so the rest of the system
        sees the dismissal. Without this, ``model._visible`` stays True
        while the popup is gone — state drift.
        """
        self._widget_state.set(open_key, self._CLOSED)
        self._widget_state.set(dismiss_key, self._OPEN)
        if self._elem.visible:
            self._elem.model.close()

    def _render_child(self, child: object) -> None:
        """Dispatch one dialog child to its renderer.

        Button is the only valid dialog child kind on the wire today;
        richer composites extend this dispatch. An unrecognized child
        type raises rather than silently dropping — the wire decoder
        rejects unknown kinds, so an unhandled type here is a renderer
        bug, not user input.
        """
        if isinstance(child, ButtonElement):
            self._button_renderer.render(child)
            return
        msg = f"unsupported dialog child kind: {type(child).__name__}"
        raise TypeError(msg)
