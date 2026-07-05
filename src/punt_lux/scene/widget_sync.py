"""Mirror a patched element's value into WidgetState."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.protocol import (
    CheckboxElement,
    ComboElement,
    InputNumberElement,
    InputTextElement,
    RadioElement,
    SelectableElement,
    SliderElement,
    WindowElement,
)

if TYPE_CHECKING:
    from punt_lux.protocol import Element
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["WidgetSync"]


@final
class WidgetSync:
    """Reflect a post-patch element's value into WidgetState and mark moved windows.

    Split out of :class:`PatchApplier`: applying a patch and mirroring its
    result into the render-facing :class:`WidgetState` are distinct concerns.
    The dirty-windows set is shared with the manager, mutated in place so the
    rendering layer sees marked windows through ``SceneManager.dirty_windows``.
    """

    __slots__ = ("_dirty_windows",)

    _dirty_windows: set[str]

    def __new__(cls, *, dirty_windows: set[str]) -> Self:
        self = super().__new__(cls)
        self._dirty_windows = dirty_windows
        return self

    def sync(
        self, elem: Element, valid: dict[str, Any], ws: WidgetState | None
    ) -> None:
        """Mirror a post-patch element's value into WidgetState.

        A value-bearing input writes its new ``widget_value()``; a kind
        excluded from that dispatch (e.g. ColorPickerElement) has its cache
        DISCARDED so the next render re-seeds from the patched fields rather
        than reading a poisoned ``None``. A moved/resized window is marked
        dirty so its next frame re-applies position.
        """
        eid = getattr(elem, "id", None)
        has_value_key = valid.keys() & {"value", "selected", "items"}
        if eid is not None and ws is not None and has_value_key:
            new_value = self._widget_value(elem)
            if new_value is None:
                ws.discard(eid)
            else:
                ws.set(eid, new_value)
        has_pos_key = valid.keys() & {"x", "y", "width", "height"}
        if eid is not None and isinstance(elem, WindowElement) and has_pos_key:
            self._dirty_windows.add(eid)

    def _widget_value(self, elem: Element) -> Any:
        """Extract the current widget value from an element for WidgetState.

        Direct ``isinstance`` dispatch against the seven value-bearing input
        element classes — each owns a ``widget_value()`` method that returns
        the field mirrored into ``WidgetState`` after a patch.
        ``ColorPickerElement`` is intentionally excluded: its renderer seeds
        ``WidgetState`` with an ``ImVec4`` via ``ensure()``, so returning the
        raw hex string here would corrupt that state.
        """
        if isinstance(
            elem,
            (
                CheckboxElement,
                ComboElement,
                InputNumberElement,
                InputTextElement,
                RadioElement,
                SelectableElement,
                SliderElement,
            ),
        ):
            return elem.widget_value()
        return None
