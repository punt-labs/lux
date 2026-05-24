"""ImGuiTextRenderer adapter — factory dispatch and Renderer Protocol shape.

Per docs/oo-refactor/pr3-v2.1-design.md §7(vi): the production
``ImGuiRendererFactory`` returns an ``ImGuiTextRenderer`` for a
``TextElement``. ``begin``/``end`` are documented no-ops for the Text
leaf — safe to invoke without an active ImGui frame. ``render`` is NOT
exercised here: it calls into ``imgui.text_wrapped`` which segfaults
without a live GL context. Render-path coverage lives in the visual
tier (manual) and the e2e tier where a display server is running.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.text import TextElement
from punt_lux.scene.widget_state import WidgetState


def _emit(_msg: object) -> None:
    """No-op Display-tier emit (matches the production wiring)."""


def _factory() -> ImGuiRendererFactory:
    return ImGuiRendererFactory(
        widget_state=WidgetState(),
        texture_cache=TextureCache(),
        emit=_emit,
    )


def test_factory_returns_imgui_text_renderer_for_text_element() -> None:
    factory = _factory()
    elem = TextElement(id="t1", content="hello")
    renderer = factory(elem)
    assert isinstance(renderer, ImGuiTextRenderer)


def test_imgui_text_renderer_lifecycle_methods_are_no_ops() -> None:
    renderer = ImGuiTextRenderer(TextElement(id="t1", content="x"), _factory())
    renderer.begin()
    renderer.end()
