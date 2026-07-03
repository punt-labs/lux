"""ImGuiRendererFactory — surface-shared mediator for ImGui per-kind renderers.

The production RendererFactory. Constructed once at Display startup and
threaded through every element constructed during decode. Holds the
three pieces of Display-tier surface-shared state — ``WidgetState``,
``TextureCache``, ``Emit`` — and dispatches by element type to the
per-kind adapter.

Per-kind renderers receive the factory (not the shared pieces) so the
factory remains the single mediator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
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

    @property
    def texture_cache(self) -> TextureCache:
        """Return the texture cache shared across renderers."""
        return self._texture_cache

    @property
    def emit(self) -> Emit:
        """Return the Display-tier emit channel (a no-op; interactions route to Hub)."""
        return self._emit

    @property
    def element_renderer(self) -> ElementRenderer:
        """Return the legacy ElementRenderer for delegated post-processing.

        The per-kind renderers delegate paint to ``ElementRenderer``
        so generic post-processing (e.g. styled-text tooltip hover) keeps
        working. Removed once every kind has its own renderer adapter.
        """
        return self._element_renderer

    def __call__(self, elem: object) -> Renderer:
        """Dispatch by element type to its ImGui adapter.

        Text only for now; Button/Panel/Dialog/Window/… cases are added
        as their families gain dedicated renderer adapters.
        """
        if isinstance(elem, TextElement):
            return ImGuiTextRenderer(elem, self)
        msg = f"no imgui renderer for {type(elem).__name__}"
        raise ValueError(msg)
