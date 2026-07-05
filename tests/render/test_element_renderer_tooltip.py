"""ElementRenderer.apply_tooltip — the shared generic-tooltip guard.

``apply_tooltip`` is the post-processing pass the legacy dispatch and the
per-kind ImGui adapters share. Its ``is_text_with_inline_tooltip`` guard
suppresses the generic tooltip for *unstyled* text with a tooltip, because
``TextRenderer`` already emits that tooltip inline via ``selectable()`` —
running the generic pass too would double it.

These tests exercise only the branches that return before touching live
ImGui (segfaults without a GL context): unstyled-text-with-tooltip (guard
returns early) and any element with no tooltip (the ``if tooltip and ...``
short-circuits before the hover query). The styled-text and hovered paths
call real ImGui and are covered by the visual/e2e tiers.
"""

from __future__ import annotations

from punt_lux.display.element_renderer import ElementRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene.widget_state import WidgetState


def _no_emit_event(_msg: RemoteEventHandlerInvocation) -> None:
    """No-op interaction emit for the test ElementRenderer."""


def _no_check_dirty(_window_id: str) -> bool:
    return False


def _renderer() -> ElementRenderer:
    widget_state = WidgetState()
    textures = TextureCache()
    return ElementRenderer(
        widget_state=widget_state,
        texture_cache=textures,
        table_renderer=TableRenderer(
            widget_state=widget_state,
            emit_event=_no_emit_event,
        ),
        emit_event=_no_emit_event,
        check_dirty_window=_no_check_dirty,
    )


def test_apply_tooltip_skips_unstyled_text_with_tooltip() -> None:
    """The inline-tooltip guard returns before any ImGui call."""
    elem = TextElement(id="t1", content="hi", tooltip="hint")
    # No live ImGui frame — a call into imgui here would segfault. It does
    # not, because the guard returns first.
    _renderer().apply_tooltip(elem)


def test_apply_tooltip_no_tooltip_is_a_noop() -> None:
    """An element without a tooltip never queries the hover state."""
    elem = TextElement(id="t2", content="hi")
    _renderer().apply_tooltip(elem)
