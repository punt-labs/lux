"""TooltipPainter — the shared generic hover-tooltip pass.

``paint`` is the post-processing the legacy dispatch and every per-kind ImGui
adapter share. Its ``_is_text_with_inline_tooltip`` guard suppresses the generic
tooltip for *unstyled* text with a tooltip, because ``TextRenderer`` already emits
that tooltip inline via ``selectable()`` — running the generic pass too would
double it.

These tests exercise only the branches that return before touching live ImGui
(which segfaults without a GL context): unstyled-text-with-tooltip (the guard
returns early) and any element with no tooltip (the ``if tooltip and ...``
short-circuits before the hover query). The styled-text and hovered paths call
real ImGui and are covered by the visual/e2e tiers.
"""

from __future__ import annotations

from punt_lux.display.renderers.tooltip_painter import TooltipPainter
from punt_lux.protocol.elements.text import TextElement


def test_paint_skips_unstyled_text_with_tooltip() -> None:
    """The inline-tooltip guard returns before any ImGui call."""
    elem = TextElement(id="t1", content="hi", tooltip="hint")
    # No live ImGui frame — a call into imgui here would segfault. It does
    # not, because the guard returns first.
    TooltipPainter().paint(elem)


def test_paint_no_tooltip_is_a_noop() -> None:
    """An element without a tooltip never queries the hover state."""
    elem = TextElement(id="t2", content="hi")
    TooltipPainter().paint(elem)
