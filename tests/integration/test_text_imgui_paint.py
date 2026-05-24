"""Text element paint path selection — display server routes Text via factory.

Per docs/oo-refactor/pr3-v2.1-design.md §7(vi): the display server's
``_render_scene`` / ``_render_scene_tab`` dispatch a ``TextElement``
through ``ImGuiRendererFactory`` rather than the PR-2
``ElementRenderer``; every other kind keeps the ``ElementRenderer``
path. This test asserts the factory contract (which renderer it
returns for a Text element) — the visual tier (manual) covers the
actual paint.
"""

from __future__ import annotations

import pytest

from punt_lux.display.element_renderer import ElementRenderer
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements import element_from_dict
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.messages.interaction import InteractionMessage
from punt_lux.scene.widget_state import WidgetState


def _emit(_msg: object) -> None:
    """Display-tier no-op emit (matches DisplayServer wiring)."""


def _no_emit_event(_msg: InteractionMessage) -> None:
    """No-op interaction emit for the test ElementRenderer."""


def _no_check_dirty(_window_id: str) -> bool:
    return False


@pytest.mark.integration
def test_decoded_text_routes_to_imgui_text_renderer() -> None:
    """A wire-decoded TextElement resolves to ImGuiTextRenderer via the factory.

    This is the integration the display server's render loop performs:
    decode the wire dict to a typed element, then ask the
    ``ImGuiRendererFactory`` for its adapter. The ``isinstance`` check on
    the result is exactly the guard ``_render_scene`` uses to choose the
    PR-3 paint path.
    """
    widget_state = WidgetState()
    textures = TextureCache()
    table_renderer = TableRenderer(
        widget_state=widget_state,
        emit_event=_no_emit_event,
    )
    element_renderer = ElementRenderer(
        widget_state=widget_state,
        texture_cache=textures,
        table_renderer=table_renderer,
        emit_event=_no_emit_event,
        check_dirty_window=_no_check_dirty,
    )
    factory = ImGuiRendererFactory(
        widget_state=widget_state,
        texture_cache=textures,
        emit=_emit,
        element_renderer=element_renderer,
    )
    elem = element_from_dict({"kind": "text", "id": "t1", "content": "Hello"})
    assert isinstance(elem, TextElement)
    renderer = factory(elem)
    assert isinstance(renderer, ImGuiTextRenderer)
