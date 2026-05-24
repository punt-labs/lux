"""ImGuiTextRenderer — Renderer-Protocol adapter for ``TextElement``.

Per docs/oo-refactor/pr3-v2.1-design.md §2: the production text
renderer delegates to the proven PR-2 ``TextRenderer`` (style branches,
color, tooltip). The adapter exists to satisfy the Renderer Protocol
shape (``render`` / ``begin`` / ``end``) so the io-model's template-method
``Element.render()`` can call it polymorphically; Text is a leaf so
``begin`` / ``end`` are no-ops.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.display.renderers.text_renderer import TextRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.text import TextElement

__all__ = ["ImGuiTextRenderer"]


# Module-level reuse of the PR-2 TextRenderer — it carries no per-element
# state (style branches read from the element each call) so a single
# instance serves every ImGuiTextRenderer adapter.
_TEXT_RENDERER = TextRenderer()


class ImGuiTextRenderer:
    """Delegate ImGui paint for a TextElement to the PR-2 ``TextRenderer``."""

    _elem: TextElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: TextElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def render(self) -> None:
        """Paint the text — delegates to the PR-2 ``TextRenderer``."""
        _TEXT_RENDERER.render(self._elem)

    def begin(self) -> None:
        """No-op — Text is a leaf, ``Element.render()`` never calls this."""

    def end(self) -> None:
        """No-op — Text is a leaf, ``Element.render()`` never calls this."""
