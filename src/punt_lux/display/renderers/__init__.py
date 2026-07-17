"""Per-kind renderer classes for the basics + inputs element families.

Each kind owns a small class with a ``render(elem)`` method.  These
replace the corresponding branches of ``ElementRenderer._RENDERERS``.
Other element families still go through the dispatch table — they will
migrate in subsequent PRs.
"""

from __future__ import annotations

from punt_lux.display.renderers.button_renderer import ButtonRenderer
from punt_lux.display.renderers.checkbox_renderer import CheckboxRenderer
from punt_lux.display.renderers.color_picker_renderer import ColorPickerRenderer
from punt_lux.display.renderers.combo_renderer import ComboRenderer
from punt_lux.display.renderers.image_renderer import ImageRenderer
from punt_lux.display.renderers.input_number_renderer import InputNumberRenderer
from punt_lux.display.renderers.input_text_renderer import InputTextRenderer
from punt_lux.display.renderers.markdown_renderer import MarkdownRenderer
from punt_lux.display.renderers.radio_renderer import RadioRenderer
from punt_lux.display.renderers.selectable_renderer import SelectableRenderer
from punt_lux.display.renderers.separator_renderer import SeparatorRenderer
from punt_lux.display.renderers.slider_renderer import SliderRenderer
from punt_lux.display.renderers.spinner_renderer import SpinnerRenderer
from punt_lux.display.renderers.text_renderer import TextRenderer

__all__ = [
    "ButtonRenderer",
    "CheckboxRenderer",
    "ColorPickerRenderer",
    "ComboRenderer",
    "ImageRenderer",
    "InputNumberRenderer",
    "InputTextRenderer",
    "MarkdownRenderer",
    "RadioRenderer",
    "SelectableRenderer",
    "SeparatorRenderer",
    "SliderRenderer",
    "SpinnerRenderer",
    "TextRenderer",
]
