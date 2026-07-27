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

from punt_lux.protocol.elements import container_dispatch

# _strip_none is re-exported for protocol.messages.scene; lives in
# _util because the codec layer above the per-element modules uses it.
from punt_lux.protocol.elements._util import strip_none as _strip_none
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.draw import DrawElement
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.modal import ModalElement
from punt_lux.protocol.elements.plot import PlotElement
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.protocol.elements.separator import SeparatorElement
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.spinner import SpinnerElement
from punt_lux.protocol.elements.tab import Tab
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.tree import TreeElement
from punt_lux.protocol.elements.window import WindowElement
from punt_lux.protocol.encoder_factory import JsonEncoderFactory

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
    "TextElement",
    "TreeElement",
    "WindowElement",
    "_element_to_dict",
    "_strip_none",
    "element_to_dict",
]
# The underscore-prefixed names above are package-internal API kept in
# __all__ so pyright's reportPrivateUsage accepts intra-protocol imports.


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
    | MarkdownElement
    | ModalElement
)


# Encode has no DI; each per-kind encoder owns its own tooltip emission.
_ENCODER_FACTORY = JsonEncoderFactory()


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element to its JSON-compatible wire dict."""
    return _ENCODER_FACTORY.encode(elem)


def element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element to a JSON-compatible dict."""
    return _element_to_dict(elem)


# Encode-side container recursion has no factory dependency. Install
# once at import time. Decode-side recursion is injected per-tier by
# the tier-boundary code: each tier calls
# ``container_dispatch.dispatch.install_from_dict(factory.element_from_dict)``
# after constructing its :class:`JsonElementFactory`.
container_dispatch.dispatch.install_to_dict(_element_to_dict)
