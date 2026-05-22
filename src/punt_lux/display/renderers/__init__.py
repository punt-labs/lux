"""Per-kind renderer classes for the basics element family.

Each kind owns a small class with a ``render(elem)`` method.  These
replace the basics branches of ``ElementRenderer._RENDERERS``.  Other
element families still go through the dispatch table — they will
migrate in subsequent PRs.
"""

from __future__ import annotations

from punt_lux.display.renderers.image_renderer import ImageRenderer
from punt_lux.display.renderers.markdown_renderer import MarkdownRenderer
from punt_lux.display.renderers.progress_renderer import ProgressRenderer
from punt_lux.display.renderers.separator_renderer import SeparatorRenderer
from punt_lux.display.renderers.spinner_renderer import SpinnerRenderer
from punt_lux.display.renderers.text_renderer import TextRenderer

__all__ = [
    "ImageRenderer",
    "MarkdownRenderer",
    "ProgressRenderer",
    "SeparatorRenderer",
    "SpinnerRenderer",
    "TextRenderer",
]
