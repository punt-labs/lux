"""ImGuiDialogRenderer — paint a DialogElement as an ImGui modal popup.

Refactored into the ``begin``/``paint``/``end`` Renderer Protocol so the
Element render skeleton drives it: ``begin`` opens the modal (or reports it
hidden) and stashes the prior-frame latch; the skeleton draws the dialog's
child Buttons through the default recursion; ``end`` closes the popup, applies
the hover tooltip, and runs the Escape/outside dismiss cascade.

Visibility is sourced from the dialog's own ``DialogModel`` so one state
machine — agent ``RemoveElement``, model dismiss, connection disconnect —
drives renderer behaviour. Widget-state latches let a dismissed-by-renderer
dialog re-open once the model becomes visible again. The renderer is
constructed fresh each frame, so the latch it stashes never leaks frames.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self, final

from imgui_bundle import imgui

from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.dialog import DialogElement

__all__ = ["ImGuiDialogRenderer"]


@final
class ImGuiDialogRenderer:
    """Paint a ``DialogElement`` as an ImGui modal popup (begin/paint/end)."""

    _elem: DialogElement
    _factory: ImGuiRendererFactory
    _was_open: bool
    _open_key: str
    _dismiss_key: str

    _OPEN: ClassVar[int] = 1
    _CLOSED: ClassVar[int] = 0

    def __new__(cls, elem: DialogElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        self._was_open = False
        # Latch keys share WidgetState's suffixes so a re-added same-id dialog
        # reopens (WidgetState.discard_for clears the same keys).
        self._open_key = f"{elem.id}{WidgetState.OPEN_SUFFIX}"
        self._dismiss_key = f"{elem.id}{WidgetState.DISMISS_SUFFIX}"
        return self

    def begin(self) -> bool:
        """Open the modal popup; return whether it is visible this frame.

        Stashes the prior-frame ``was_open`` latch on the instance so
        ``end`` can reconstruct the external-close condition from it and
        this frame's visibility.
        """
        ws = self._factory.widget_state
        was_open = ws.ensure(self._open_key, self._CLOSED) == self._OPEN
        dismissed = ws.ensure(self._dismiss_key, self._CLOSED) == self._OPEN

        if not self._elem.visible:
            if was_open or dismissed:
                ws.set(self._open_key, self._CLOSED)
                ws.set(self._dismiss_key, self._CLOSED)
            self._was_open = False
            return False

        title = self._elem.title or self._elem.id
        # Triple-hash pins the ImGui popup identity to the element id alone, so a
        # title change never re-hashes the popup and spuriously dismisses an open
        # dialog (the same fix the modal adapter carries).
        popup_id = f"{title}###{self._elem.id}"
        if not was_open and not dismissed:
            imgui.open_popup(popup_id)
            ws.set(self._open_key, self._OPEN)
            was_open = True
        self._was_open = was_open

        visible, _p_open = imgui.begin_popup_modal(popup_id, True)  # noqa: FBT003
        return visible

    def paint(self) -> None:
        """A dialog is a container; its body is its children, so paint no widget.

        The rect is recorded in ``end`` after the children have laid out — the
        skeleton runs ``paint`` before the children, so recording here would
        capture the pre-layout size of an auto-sizing popup.
        """

    def end(self, *, opened: bool) -> None:
        """Record the settled rect, close the popup, apply tooltip, run cascade.

        The record runs while the popup is still current but after the children
        have laid out, so an auto-sized dialog reports its settled size.
        """
        if opened:
            self._factory.geometry.record_window(self._elem.id, self._elem.kind)
            imgui.end_popup()
        if self._was_open and not opened:
            self._handle_external_close()
        self._factory.apply_tooltip(self._elem)

    def _handle_external_close(self) -> None:
        """Sync latches and close the model after an ImGui-driven close.

        ImGui closes the popup itself on Escape or an outside click.
        Pressing Escape on a modal IS a dismiss: the model's ``close()``
        fires its observer cascade (``mark_removed`` → parent composites)
        so the rest of the system sees it. Without this, ``model._visible``
        stays True while the popup is gone — state drift.
        """
        ws = self._factory.widget_state
        ws.set(self._open_key, self._CLOSED)
        ws.set(self._dismiss_key, self._OPEN)
        if self._elem.visible:
            self._elem.model.close()
