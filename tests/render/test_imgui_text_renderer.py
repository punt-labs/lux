"""ImGuiTextRenderer adapter — factory dispatch and Renderer Protocol shape.

Per docs/oo-refactor/pr3-v2.1-design.md §7(vi): the production
``ImGuiRendererFactory`` returns an ``ImGuiTextRenderer`` for a
``TextElement``. ``begin``/``end`` are documented no-ops for the Text
leaf — safe to invoke without an active ImGui frame. ``render`` is NOT
exercised against real ImGui here: it calls into ``imgui.text_wrapped``
which segfaults without a live GL context. Render-path coverage lives
in the visual tier (manual) and the e2e tier where a display server
is running.

The regression test for Cursor MED (PR #195 round 2) stubs the
``ElementRenderer.render_element`` method and asserts ``ImGuiTextRenderer``
delegates to it — that delegation is what preserves the styled-text
tooltip post-processing the io-model dispatch would otherwise bypass.
"""

from __future__ import annotations

from typing import Self
from unittest.mock import MagicMock

from punt_lux.display.element_renderer import ElementRenderer
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.messages.interaction import InteractionMessage
from punt_lux.scene.widget_state import WidgetState


def _emit(_msg: object) -> None:
    """No-op Display-tier emit (matches the production wiring)."""


def _no_emit_event(_msg: InteractionMessage) -> None:
    """No-op interaction emit (matches the production wiring for the test stub)."""


def _no_check_dirty(_window_id: str) -> bool:
    """Stub dirty-window check that always returns False."""
    return False


def _element_renderer(
    widget_state: WidgetState, textures: TextureCache
) -> ElementRenderer:
    table_renderer = TableRenderer(
        widget_state=widget_state,
        emit_event=_no_emit_event,
    )
    return ElementRenderer(
        widget_state=widget_state,
        texture_cache=textures,
        table_renderer=table_renderer,
        emit_event=_no_emit_event,
        check_dirty_window=_no_check_dirty,
    )


def _factory() -> ImGuiRendererFactory:
    widget_state = WidgetState()
    textures = TextureCache()
    return ImGuiRendererFactory(
        widget_state=widget_state,
        texture_cache=textures,
        emit=_emit,
        element_renderer=_element_renderer(widget_state, textures),
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


class _StubFactory:
    """Minimal RendererFactory stub that only exposes ``element_renderer``.

    Lets ``ImGuiTextRenderer.render`` be exercised without a live ImGui
    context — only the delegation hop is under test.
    """

    _element_renderer: ElementRenderer

    def __new__(cls, element_renderer: ElementRenderer) -> Self:
        self = super().__new__(cls)
        self._element_renderer = element_renderer
        return self

    @property
    def element_renderer(self) -> ElementRenderer:
        return self._element_renderer


def test_render_delegates_to_element_renderer_so_styled_tooltip_fires() -> None:
    """Cursor MED regression: render() must go through ElementRenderer.

    ``ElementRenderer.render_element`` runs the native ``TextRenderer``
    paint AND the generic tooltip post-processing for styled text.
    Calling ``TextRenderer.render`` directly would skip that post step,
    dropping the tooltip for styled text. Stub the method and assert
    ``ImGuiTextRenderer.render`` dispatches into it with the styled
    tooltipped element.
    """
    widget_state = WidgetState()
    textures = TextureCache()
    element_renderer = _element_renderer(widget_state, textures)
    element_renderer.render_element = MagicMock()  # type: ignore[method-assign]
    elem = TextElement(
        id="styled-tt",
        content="hello",
        style="heading",
        tooltip="more info",
    )

    ImGuiTextRenderer(elem, _StubFactory(element_renderer)).render()  # type: ignore[arg-type]

    element_renderer.render_element.assert_called_once_with(elem)
