"""ImGuiTextRenderer — Renderer-Protocol adapter for ``TextElement``.

The production text renderer delegates to the legacy
``ElementRenderer.render_element`` which dispatches the TextElement to
its native ``TextRenderer`` (style branches, color) AND runs the generic
post-processing pass (styled-text tooltip hover). Delegating to
``ElementRenderer`` — rather than ``TextRenderer`` directly — preserves
the tooltip post-processing that per-kind renderer dispatch would
otherwise bypass. The adapter exists to satisfy the Renderer Protocol
shape (``render`` / ``begin`` / ``end``) so the template-method
``Element.render()`` can call it polymorphically; Text is a leaf so
``begin`` / ``end`` are no-ops.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.text import TextElement

__all__ = ["ImGuiTextRenderer"]


class ImGuiTextRenderer:
    """Delegate ImGui paint for a TextElement to the legacy ``ElementRenderer``."""

    _elem: TextElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: TextElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def render(self) -> None:
        """Paint the text — delegates to ``ElementRenderer.render_element``.

        ``ElementRenderer`` runs the native ``TextRenderer`` (style + color)
        AND the generic tooltip post-processing, so styled text with a
        tooltip still gets the hover hint.
        """
        self._factory.element_renderer.render_element(self._elem)

    def begin(self) -> None:
        """No-op — Text is a leaf, ``Element.render()`` never calls this."""

    def end(self) -> None:
        """No-op — Text is a leaf, ``Element.render()`` never calls this."""
