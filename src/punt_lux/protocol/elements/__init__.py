"""Element protocol package — wire types and serialization dispatch.

Sub-modules house each family of element types together with their codec
helpers:

- ``basics``: static display primitives (Text, Image, Separator, …)
- ``inputs``: interactive controls (Button, Slider, Checkbox, …)
- ``layout``: containers (Group, Window, TabBar, …)
- ``graphics``: 2D canvas and chart (Draw, Plot)
- ``table``: tabular data with filters and detail panels
- ``patch``: single-element update payload

The ``codec`` sub-module holds the ``ElementCodec`` class — the dispatch
table that maps wire ``kind`` strings to (class, to_dict, from_dict)
triples.  Tests can construct isolated codecs; the production codec is
the module-level ``_codec`` instance populated at import time.

This ``__init__`` is the package surface: it re-exports every public
name, assembles the ``Element`` union from per-family contributions, and
provides the ``element_to_dict`` dispatcher. Decoding lives on
:class:`JsonElementFactory` — every tier constructs one at startup with
its own ``RendererFactory`` / ``Emit`` / ``PublishSink`` and calls
``factory.element_from_dict(d)``. ``build_element_codec()`` returns the
shared ``ElementCodec`` instance every factory uses for non-ABC kinds.
"""

from __future__ import annotations

from typing import Any

from punt_lux.protocol.elements import layout

# _strip_none is re-exported for protocol.messages.scene; lives in
# _util because the codec layer above the per-element modules uses it.
from punt_lux.protocol.elements._util import strip_none as _strip_none
from punt_lux.protocol.elements.basics import BasicsRegistry
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.codec import ElementCodec
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.graphics import (
    DrawElement,
    PlotElement,
    register_codecs as _register_graphics,
)
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.inputs import InputsRegistry
from punt_lux.protocol.elements.layout import (
    CollapsingHeaderElement,
    GroupElement,
    ModalElement,
    TabBarElement,
    TreeElement,
    WindowElement,
    register_codecs as _register_layout,
)
from punt_lux.protocol.elements.markdown import MarkdownElement

# _patch_to_dict / _patch_from_dict are re-exported for protocol.messages.scene
# (used by UpdateMessage codec).
from punt_lux.protocol.elements.patch import (
    Patch,
    _patch_from_dict as _patch_from_dict,
    _patch_to_dict as _patch_to_dict,
)
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.protocol.elements.separator import SeparatorElement
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.spinner import SpinnerElement
from punt_lux.protocol.elements.table import (
    TableDetail,
    TableElement,
    TableFilter,
    register_codecs as _register_table,
)
from punt_lux.protocol.elements.text import TextElement
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
    "ElementCodec",
    "GroupElement",
    "ImageElement",
    "InputNumberElement",
    "InputTextElement",
    "MarkdownElement",
    "ModalElement",
    "Patch",
    "PlotElement",
    "ProgressElement",
    "RadioElement",
    "SelectableElement",
    "SeparatorElement",
    "SliderElement",
    "SpinnerElement",
    "TabBarElement",
    "TableDetail",
    "TableElement",
    "TableFilter",
    "TextElement",
    "TreeElement",
    "WindowElement",
    "_element_to_dict",
    "_patch_from_dict",
    "_patch_to_dict",
    "_strip_none",
    "build_element_codec",
    "element_to_dict",
]
# The four underscore-prefixed names above are package-internal API:
# used by protocol/messages.py and other internal codecs, not by external
# callers. They remain in __all__ so pyright's reportPrivateUsage does not
# fire on intentional cross-module imports within the protocol package.
# The leading underscore signals "do not import from outside protocol/".


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


def build_element_codec() -> ElementCodec:
    """Return a fresh :class:`ElementCodec` with every kind registered.

    Each :class:`JsonElementFactory` owns its own codec instance — the
    codec carries no DI, but binding a separate instance per factory
    keeps factory construction self-contained.
    """
    codec = ElementCodec()
    BasicsRegistry().apply(codec.register)
    InputsRegistry().apply(codec.register)
    _register_layout(codec.register)
    _register_graphics(codec.register)
    _register_table(codec.register)
    return codec


# Module-level codec used for the encode (to_dict) side, which has no
# DI dependency. The decode side (from_dict) lives on
# :class:`JsonElementFactory` so the tier-injected ``PublishSink`` /
# ``RendererFactory`` / ``Emit`` flow into every decoded element.
_to_dict_codec: ElementCodec = build_element_codec()
_ENCODER_FACTORY = JsonEncoderFactory()


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    if isinstance(elem, TextElement | ButtonElement | CheckboxElement | DialogElement):
        # Each per-kind encoder owns its own tooltip emission.
        return _ENCODER_FACTORY.encode(elem)
    result = _to_dict_codec.to_dict(elem)
    # The remaining dataclass kinds' per-kind codecs don't emit tooltip;
    # the Element Protocol guarantees the attribute (PY-TS-10: no hasattr).
    if elem.tooltip is not None:
        result["tooltip"] = elem.tooltip
    return result


def element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    return _element_to_dict(elem)


# Encode-side container recursion has no factory dependency. Install
# once at import time. Decode-side recursion is injected per-tier by
# the tier-boundary code: each tier calls
# ``layout.install_from_dict(factory.element_from_dict)`` after
# constructing its :class:`JsonElementFactory`.
layout.install_to_dict(_element_to_dict)
