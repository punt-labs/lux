"""ImGuiRendererFactory — surface-shared mediator for ImGui per-kind renderers.

Constructed once at Display startup and bound onto received elements by the
Display's post-receive rebind (``Element.bind_renderer_factory``). Holds the
Display-tier surface-shared state (``WidgetState``, ``TextureCache``, ``Emit``)
and dispatches by element type to the per-kind adapter, its sole mediator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

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
from punt_lux.display.renderers.imgui.slider import ImGuiSliderRenderer
from punt_lux.display.renderers.imgui.tab_bar import ImGuiTabBarRenderer
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
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
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.element_renderer import ElementRenderer
    from punt_lux.display.texture_cache import TextureCache
    from punt_lux.protocol.renderer import Emit, Renderer
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["ImGuiRendererFactory"]


class ImGuiRendererFactory:
    """Resolve an Element to its ImGui Renderer adapter."""

    _widget_state: WidgetState
    _texture_cache: TextureCache
    _emit: Emit
    _element_renderer: ElementRenderer

    # Element type -> adapter constructor. This table drives ``__call__``
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
    )

    def __new__(
        cls,
        *,
        widget_state: WidgetState,
        texture_cache: TextureCache,
        emit: Emit,
        element_renderer: ElementRenderer,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._texture_cache = texture_cache
        self._emit = emit
        self._element_renderer = element_renderer
        return self

    @property
    def widget_state(self) -> WidgetState:
        """Return the per-scene widget state the factory mediates access to."""
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        """Re-thread the factory to the scene being rendered.

        The ABC tab-bar adapter reads echo-suppression state through the
        factory, so a scene switch must reach it here or the adapter never sees
        a re-push reset.
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

    @property
    def element_renderer(self) -> ElementRenderer:
        """Return the ElementRenderer that owns the per-kind renderers.

        Adapters paint through its per-scene sub-renderers and shared
        ``apply_tooltip`` post-processing.
        """
        return self._element_renderer

    def __call__(self, elem: object) -> Renderer:
        """Return the ImGui adapter for ``elem``, or raise if unsupported."""
        for element_type, adapter in self._DISPATCH:
            if isinstance(elem, element_type):
                return adapter(elem, self)
        msg = f"no imgui renderer for {type(elem).__name__}"
        raise ValueError(msg)
