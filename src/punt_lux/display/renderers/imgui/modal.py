# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiModalRenderer — paint an ABC ``ModalElement`` as an ImGui modal popup.

The interactive-composite seam, copied from ``ImGuiDialogRenderer``: ``begin``
opens the popup (or reports it hidden) and stashes the prior-frame latch; the
Element render skeleton draws the body through the default child recursion;
``end`` closes the popup, applies the tooltip, and runs the external-close
cascade. Visibility is sourced from the modal's own ``ModalModel``.

A plain modal has no child controllers to resolve an Escape/outside close, so
this adapter fires ``ModalClosed`` through the element's handler registry (which
the Display wrapped for remote dispatch); the Hub runs the dismiss and re-pushes,
and the widget-state dismiss latch keeps the popup shut until that re-push lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self, final

from imgui_bundle import imgui

from punt_lux.domain.container_interaction import ModalClosed
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.modal import ModalElement

__all__ = ["ImGuiModalRenderer"]


@final
class ImGuiModalRenderer:
    """Paint an ABC ``ModalElement`` as an ImGui modal popup (begin/paint/end)."""

    _elem: ModalElement
    _factory: ImGuiRendererFactory
    _was_open: bool
    _open_key: str
    _dismiss_key: str

    _OPEN: ClassVar[int] = 1
    _CLOSED: ClassVar[int] = 0
    # Minimum popup width. Without a size seed ImGui auto-sizes the modal to its
    # minimal content width and the ABC text renderer's work-rect wrapping
    # (DES-026) collapses every child to a one-character needle. The floor is
    # expandable (unbounded max) so wider content still grows; no wire size field.
    _MIN_WIDTH: ClassVar[float] = 320.0

    def __new__(cls, elem: ModalElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        self._was_open = False
        self._open_key = f"{elem.id}{WidgetState.OPEN_SUFFIX}"
        self._dismiss_key = f"{elem.id}{WidgetState.DISMISS_SUFFIX}"
        return self

    def begin(self) -> bool:
        """Open the modal popup; return whether it is visible this frame.

        Stashes the prior-frame ``was_open`` latch on the instance so ``end``
        can reconstruct the external-close condition from it and this frame's
        visibility.
        """
        ws = self._factory.widget_state
        was_open = ws.ensure(self._open_key, self._CLOSED) == self._OPEN
        dismissed = ws.ensure(self._dismiss_key, self._CLOSED) == self._OPEN

        if not self._elem.open:
            if was_open or dismissed:
                ws.set(self._open_key, self._CLOSED)
                ws.set(self._dismiss_key, self._CLOSED)
            self._was_open = False
            return False

        title = self._elem.title or self._elem.id
        # Triple-hash pins the popup identity to the element id, so a title change
        # never re-hashes the popup and spuriously dismisses an open modal.
        popup_id = f"{title}###{self._elem.id}"
        if not was_open and not dismissed:
            imgui.open_popup(popup_id)
            ws.set(self._open_key, self._OPEN)
            was_open = True
        self._was_open = was_open

        # Floor the width before the popup is created (see ``_MIN_WIDTH``).
        imgui.set_next_window_size_constraints(
            (self._MIN_WIDTH, 0.0), (imgui.FLT_MAX, imgui.FLT_MAX)
        )
        visible, _p_open = imgui.begin_popup_modal(popup_id, True)  # noqa: FBT003
        return visible

    def paint(self) -> None:
        """No-op — the modal's only body is its children (default recursion)."""

    def end(self, *, opened: bool) -> None:
        """Close the popup (only if open), apply the tooltip, run the cascade."""
        if opened:
            imgui.end_popup()
        if self._was_open and not opened:
            self._handle_external_close()
        self._factory.apply_tooltip(self._elem)

    def _handle_external_close(self) -> None:
        """Latch the dismiss and route the close to the Hub.

        ImGui closes the popup itself on Escape or an outside click. The latch
        keeps it shut until the Hub's removal re-push lands, and firing
        ``ModalClosed`` through the element's wrapped registry sends the close to
        the Hub, where the built-in dismiss handler removes the modal. The event
        is only fired once — the ``open`` guard skips a modal already dismissed
        on the Hub whose replica has not yet been dropped.
        """
        ws = self._factory.widget_state
        ws.set(self._open_key, self._CLOSED)
        ws.set(self._dismiss_key, self._OPEN)
        if self._elem.open:
            self._elem.fire(
                ModalClosed(
                    scene_id=SceneId("__display__"),
                    element_id=ElementId(self._elem.id),
                    owner_id=ClientId("__display__"),
                )
            )
