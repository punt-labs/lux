# pyright: reportMissingModuleSource=false
"""ImGuiImageRenderer — Renderer-Protocol adapter for ``ImageElement``.

Paints through a per-paint ``ImageRenderer`` (which uploads path-sourced images
through the factory's shared ``TextureCache`` and falls back to alt text) plus
the shared tooltip pass the factory owns. An image is a leaf, so ``begin``
proceeds and ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.image_renderer import ImageRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.image import ImageElement

__all__ = ["ImGuiImageRenderer"]


@final
class ImGuiImageRenderer:
    """Paint an ImageElement via ImageRenderer + the shared tooltip pass."""

    _elem: ImageElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: ImageElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Upload/draw the image (texture or alt fallback) + the tooltip pass."""
        ImageRenderer(self._factory.texture_cache).render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
