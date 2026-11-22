"""Element protocol package — wire types and serialization dispatch.

Sub-modules house each family of element types together with their codec
helpers:

- ``basics``: static display primitives (Text, Image, Separator, …)
- ``inputs``: interactive controls (Button, Slider, Checkbox, …)
- ``layout``: containers (Group, Window, TabBar, …)
- ``graphics``: 2D canvas and chart (Draw, Plot)
- ``table``: tabular data with filters and detail panels

This ``__init__`` is the package surface: it re-exports every public
name, assembles the ``Element`` union from per-family contributions, and
provides the ``element_to_dict`` encode dispatcher. Every kind is on the
Element-ABC path; decoding lives on :class:`JsonElementFactory`, which each
tier constructs at startup with its own ``RendererFactory`` / ``Emit`` /
``PublishSink`` and drives via ``factory.element_from_dict(d)``.
"""

from __future__ import annotations

from typing import Any

from punt_lux.wire.model.elements.button import ButtonElement
from punt_lux.wire.model.elements.checkbox import CheckboxElement
from punt_lux.wire.model.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.wire.model.elements.color_picker import ColorPickerElement
from punt_lux.wire.model.elements.combo import ComboElement
from punt_lux.wire.model.elements.container_dispatch import dispatch
from punt_lux.wire.model.elements.dialog import DialogElement
from punt_lux.wire.model.elements.draw import DrawElement
from punt_lux.wire.model.elements.group import GroupElement
from punt_lux.wire.model.elements.image import ImageElement
from punt_lux.wire.model.elements.input_number import InputNumberElement
from punt_lux.wire.model.elements.input_text import InputTextElement
from punt_lux.wire.model.elements.markdown import MarkdownElement
from punt_lux.wire.model.elements.modal import ModalElement
from punt_lux.wire.model.elements.plot import PlotElement
from punt_lux.wire.model.elements.progress import ProgressElement
from punt_lux.wire.model.elements.radio import RadioElement
from punt_lux.wire.model.elements.selectable import SelectableElement
from punt_lux.wire.model.elements.separator import SeparatorElement
from punt_lux.wire.model.elements.slider import SliderElement
from punt_lux.wire.model.elements.spinner import SpinnerElement
from punt_lux.wire.model.elements.tab import Tab
from punt_lux.wire.model.elements.tab_bar import TabBarElement
from punt_lux.wire.model.elements.table import TableElement
from punt_lux.wire.model.elements.terminal import TerminalElement
from punt_lux.wire.model.elements.text import TextElement
from punt_lux.wire.model.elements.tree import TreeElement
from punt_lux.wire.model.elements.window import WindowElement
from punt_lux.wire.model.encoder_factory import JsonEncoderFactory

__all__ = [
    "ButtonElement",
    "CheckboxElement",
    "CollapsingHeaderElement",
    "ColorPickerElement",
    "ComboElement",
    "DialogElement",
    "DrawElement",
    "Element",
    "GroupElement",
    "ImageElement",
    "InputNumberElement",
    "InputTextElement",
    "MarkdownElement",
    "ModalElement",
    "PlotElement",
    "ProgressElement",
    "RadioElement",
    "SelectableElement",
    "SeparatorElement",
    "SliderElement",
    "SpinnerElement",
    "Tab",
    "TabBarElement",
    "TableElement",
    "TerminalElement",
    "TextElement",
    "TreeElement",
    "WindowElement",
    "element_to_dict",
]


Element = (
    ImageElement
    | TextElement
    | ButtonElement
    | DialogElement
    | SeparatorElement
    | SliderElement
    | CheckboxElement
    | ComboElement
    | InputTextElement
    | InputNumberElement
    | RadioElement
    | ColorPickerElement
    | DrawElement
    | GroupElement
    | TabBarElement
    | CollapsingHeaderElement
    | WindowElement
    | SelectableElement
    | TreeElement
    | TableElement
    | PlotElement
    | ProgressElement
    | SpinnerElement
    | TerminalElement
    | MarkdownElement
    | ModalElement
)


# Encode has no DI; each per-kind encoder owns its own tooltip emission.
_ENCODER_FACTORY = JsonEncoderFactory()


def element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element to its JSON-compatible wire dict."""
    return _ENCODER_FACTORY.encode(elem)


# Encode-side container recursion has no factory dependency. Install
# once at import time. Decode-side recursion is injected per-tier by
# the tier-boundary code: each tier calls
# ``container_dispatch.dispatch.install_from_dict(factory.element_from_dict)``
# after constructing its :class:`JsonElementFactory`.
dispatch.install_to_dict(element_to_dict)
