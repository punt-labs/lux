"""ImGuiRendererFactory — surface-shared mediator for ImGui per-kind renderers.

Per docs/oo-refactor/pr3-v2.1-design.md §2: the production
RendererFactory. Constructed once at Display startup and threaded
through every io-model element constructed during decode. Holds the
three pieces of Display-tier surface-shared state — ``WidgetState``,
``TextureCache``, ``Emit`` — and dispatches by element type to the
per-kind adapter.

Per-kind renderers receive the factory (not the shared pieces) so the
factory remains the single mediator; matches the spike's
``TextRendererFactory`` shape (spike ``renderers/text.py:49``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from punt_lux.display.texture_cache import TextureCache
    from punt_lux.protocol.renderer import Emit, Renderer
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["ImGuiRendererFactory"]


class ImGuiRendererFactory:
    """Resolve an io-model Element to its ImGui Renderer adapter."""

    _widget_state: WidgetState
    _texture_cache: TextureCache
    _emit: Emit

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

    @property
    def texture_cache(self) -> TextureCache:
        """Return the texture cache shared across renderers."""
        return self._texture_cache

    @property
    def emit(self) -> Emit:
        """Return the Display-tier emit channel (no-op per spike display.py:167)."""
        return self._emit

    def __call__(self, elem: object) -> Renderer:
        """Dispatch by element type to its ImGui adapter.

        PR 3 ships Text only; PRs 4-11 add Button/Panel/Dialog/Window/…
        cases as their families migrate to the io-model.
        """
        if isinstance(elem, TextElement):
            return ImGuiTextRenderer(elem, self)
        msg = f"no imgui renderer for {type(elem).__name__}"
        raise ValueError(msg)
