"""ImGuiTextRenderer adapter — factory dispatch and Renderer Protocol shape.

The production ``ImGuiRendererFactory`` returns an ``ImGuiTextRenderer``
for a ``TextElement``. ``begin``/``end`` are documented no-ops for the
Text leaf — safe to invoke without an active ImGui frame. ``render`` is
NOT exercised against real ImGui here: it calls into ``imgui.text_wrapped``
which segfaults without a live GL context. Render-path coverage lives in the
visual tier (manual) and the e2e tier where a display server is running.

The paint regression test patches the per-paint ``TextRenderer`` and the
factory's ``apply_tooltip`` so the delegation hop — construct-render then the
shared tooltip pass — is the only thing under test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.renderers.imgui import text as text_module
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.text import TextElement
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest


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


def test_imgui_text_renderer_begin_opens_and_end_is_a_no_op() -> None:
    renderer = ImGuiTextRenderer(TextElement(id="t1", content="x"), _factory())
    # Leaf: begin proceeds (True), end closes nothing — safe without a frame.
    assert renderer.begin() is True
    renderer.end(opened=True)


def test_paint_constructs_text_renderer_then_runs_shared_tooltip_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """paint() constructs a TextRenderer, renders, then runs the factory tooltip.

    Styled text keeps its hover hint: the adapter paints the per-kind
    ``TextRenderer`` and defers the tooltip to the factory's shared pass.
    """
    render = MagicMock()
    monkeypatch.setattr(text_module, "TextRenderer", lambda: render)
    factory = MagicMock()
    elem = TextElement(id="styled-tt", content="hello", style="heading", tooltip="hi")

    ImGuiTextRenderer(elem, factory).paint()

    render.render.assert_called_once_with(elem)
    factory.apply_tooltip.assert_called_once_with(elem)
