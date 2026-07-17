"""ImGuiRendererFactory — surface-shared mediator for ImGui per-kind renderers.

Constructed once at Display startup, holding the Display-tier surface-shared
state (``WidgetState``, ``TextureCache``, ``Emit``). It dispatches by element
type to the per-kind adapter; ``handles`` lets ``render_element`` route every
migrated kind here (the one render-side authority, retiring the parallel
native-dispatch table), and every adapter shares the one ``apply_tooltip`` pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self, TypeGuard

from punt_lux.display.renderers.imgui.button import ImGuiButtonRenderer
from punt_lux.display.renderers.imgui.checkbox import ImGuiCheckboxRenderer
from punt_lux.display.renderers.imgui.collapsing_header import (
    ImGuiCollapsingHeaderRenderer,
)
from punt_lux.display.renderers.imgui.color_picker import ImGuiColorPickerRenderer
from punt_lux.display.renderers.imgui.combo import ImGuiComboRenderer
from punt_lux.display.renderers.imgui.dialog import ImGuiDialogRenderer
from punt_lux.display.renderers.imgui.group import ImGuiGroupRenderer
from punt_lux.display.renderers.imgui.input_number import ImGuiInputNumberRenderer
from punt_lux.display.renderers.imgui.input_text import ImGuiInputTextRenderer
from punt_lux.display.renderers.imgui.progress import ImGuiProgressRenderer
from punt_lux.display.renderers.imgui.radio import ImGuiRadioRenderer
from punt_lux.display.renderers.imgui.selectable import ImGuiSelectableRenderer
from punt_lux.display.renderers.imgui.slider import ImGuiSliderRenderer
from punt_lux.display.renderers.imgui.tab_bar import ImGuiTabBarRenderer
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.renderers.tooltip_painter import TooltipPainter
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.texture_cache import TextureCache
    from punt_lux.protocol import Element
    from punt_lux.protocol.renderer import Emit, Renderer
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["ImGuiRendererFactory"]

# One stateless painter serves every element's shared hover-tooltip pass.
_TOOLTIP = TooltipPainter()


class ImGuiRendererFactory:
    """Resolve an Element to its ImGui Renderer adapter."""

    _widget_state: WidgetState
    _texture_cache: TextureCache
    _emit: Emit

    # Element type -> adapter constructor driving ``__call__``/``handles``
    # dispatch. Every adapter shares the ``(elem, factory)`` constructor shape.
    _DISPATCH: ClassVar[tuple[tuple[type, Callable[..., Renderer]], ...]] = (
        (TextElement, ImGuiTextRenderer),
        (ButtonElement, ImGuiButtonRenderer),
        (CheckboxElement, ImGuiCheckboxRenderer),
        (InputTextElement, ImGuiInputTextRenderer),
        (InputNumberElement, ImGuiInputNumberRenderer),
        (DialogElement, ImGuiDialogRenderer),
        (GroupElement, ImGuiGroupRenderer),
        (CollapsingHeaderElement, ImGuiCollapsingHeaderRenderer),
        (TabBarElement, ImGuiTabBarRenderer),
        (ProgressElement, ImGuiProgressRenderer),
        (SliderElement, ImGuiSliderRenderer),
        (ColorPickerElement, ImGuiColorPickerRenderer),
        (ComboElement, ImGuiComboRenderer),
        (RadioElement, ImGuiRadioRenderer),
        (SelectableElement, ImGuiSelectableRenderer),
    )

    def __new__(
        cls,
        *,
        widget_state: WidgetState,
        texture_cache: TextureCache,
        emit: Emit,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._texture_cache = texture_cache
        self._emit = emit
        return self

    @property
    def widget_state(self) -> WidgetState:
        """Return the per-scene widget state the factory mediates access to."""
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        """Re-thread the factory to the scene being rendered.

        ABC adapters read per-scene state (echo suppression, edit buffers)
        through the factory, so a scene switch must reach it here.
        """
        self._widget_state = value

    @property
    def texture_cache(self) -> TextureCache:
        """Return the texture cache shared across renderers."""
        return self._texture_cache

    @property
    def emit(self) -> Emit:
        """Return the Display-tier emit channel (a no-op; clicks route to Hub)."""
        return self._emit

    def handles(self, elem: object) -> TypeGuard[AbcElement]:
        """Return whether ``elem`` paints through one of this factory's adapters.

        A boolean predicate (PY-EH-4) ``render_element`` branches on; every
        dispatched type is an Element-ABC subclass, so a True answer narrows
        ``elem`` to ``AbcElement`` (``__call__`` still raises for an unknown type).
        """
        return any(isinstance(elem, element_type) for element_type, _ in self._DISPATCH)

    def apply_tooltip(self, elem: Element) -> None:
        """Paint ``elem``'s shared generic hover tooltip, if it has one."""
        _TOOLTIP.paint(elem)

    def __call__(self, elem: object) -> Renderer:
        """Return the ImGui adapter for ``elem``, or raise if unsupported."""
        for element_type, adapter in self._DISPATCH:
            if isinstance(elem, element_type):
                return adapter(elem, self)
        msg = f"no imgui renderer for {type(elem).__name__}"
        raise ValueError(msg)
