"""ImGuiRendererFactory — surface-shared mediator for ImGui per-kind renderers.

Constructed once at Display startup with the Display-tier shared state; it
dispatches by element type to the per-kind adapter and shares one tooltip pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

from punt_lux.display.geometry_capture import GeometryCapture
from punt_lux.display.renderers.imgui.bindings import ImGuiRendererBindings
from punt_lux.display.renderers.tooltip_painter import TooltipPainter

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.replica.widget_state import WidgetState
    from punt_lux.display.texture_cache import TextureCache
    from punt_lux.protocol import Element
    from punt_lux.protocol.renderer import Emit, Renderer

__all__ = ["ImGuiRendererFactory"]

# One stateless painter serves every element's shared hover-tooltip pass.
_TOOLTIP = TooltipPainter()


class ImGuiRendererFactory:
    """Resolve an Element to its ImGui Renderer adapter."""

    _widget_state: WidgetState
    _texture_cache: TextureCache
    _emit: Emit
    # The one geometry capture the render loop writes and a query reads; owned
    # here so a window-like adapter records through ``geometry`` directly.
    _geometry: GeometryCapture

    # Element type -> adapter for ``__call__``; all share the ``(elem, factory)`` shape.
    _DISPATCH: ClassVar[tuple[tuple[type, Callable[..., Renderer]], ...]] = (
        ImGuiRendererBindings.table()
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
        self._geometry = GeometryCapture()
        return self

    @property
    def widget_state(self) -> WidgetState:
        """Return the per-scene widget state the factory mediates access to."""
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        """Bind renderers to the active scene's shared widget state."""
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
    def geometry(self) -> GeometryCapture:
        """Return the render loop's geometry capture — one per Display."""
        return self._geometry

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
