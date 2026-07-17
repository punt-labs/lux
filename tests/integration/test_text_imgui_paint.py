"""Text element paint path selection — display server routes Text via factory.

The display server's ``_render_scene`` / ``_render_scene_tab`` dispatch a
``TextElement`` through ``ImGuiRendererFactory`` rather than the legacy
``ElementRenderer``; every other kind keeps the ``ElementRenderer``
path. This test asserts the factory contract (which renderer it
returns for a Text element) — the visual tier (manual) covers the
actual paint.
"""

from __future__ import annotations

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.display_client import agent_element_factory
from punt_lux.protocol.elements.text import TextElement
from punt_lux.scene.widget_state import WidgetState


def _emit(_msg: object) -> None:
    """Display-tier no-op emit (matches DisplayServer wiring)."""


@pytest.mark.integration
def test_decoded_text_routes_to_imgui_text_renderer() -> None:
    """A wire-decoded TextElement resolves to ImGuiTextRenderer via the factory.

    This is the integration the display server's render loop performs:
    decode the wire dict to a typed element, then ask the
    ``ImGuiRendererFactory`` for its adapter. The ``isinstance`` check on
    the result is exactly the guard ``_render_scene`` uses to choose the
    ImGui factory paint path.
    """
    factory = ImGuiRendererFactory(
        widget_state=WidgetState(),
        texture_cache=TextureCache(),
        emit=_emit,
    )
    elem = agent_element_factory().element_from_dict(
        {"kind": "text", "id": "t1", "content": "Hello"}
    )
    assert isinstance(elem, TextElement)
    renderer = factory(elem)
    assert isinstance(renderer, ImGuiTextRenderer)
