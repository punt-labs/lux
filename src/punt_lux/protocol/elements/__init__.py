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

This ``__init__`` is the package surface: it re-exports every public name,
assembles the ``Element`` union from per-family contributions, and provides
the ``element_to_dict`` / ``element_from_dict`` dispatchers.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from punt_lux.protocol.elements import layout

# _strip_none is re-exported for protocol.messages.scene; lives in
# _util because the codec layer above the per-element modules uses it.
from punt_lux.protocol.elements._util import strip_none as _strip_none
from punt_lux.protocol.elements.basics import BasicsRegistry
from punt_lux.protocol.elements.codec import ElementCodec
from punt_lux.protocol.elements.graphics import (
    DrawElement,
    PlotElement,
    register_codecs as _register_graphics,
)
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.inputs import (
    ButtonElement,
    CheckboxElement,
    ColorPickerElement,
    ComboElement,
    InputNumberElement,
    InputTextElement,
    RadioElement,
    SelectableElement,
    SliderElement,
    register_codecs as _register_inputs,
)
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
from punt_lux.protocol.elements.separator import SeparatorElement
from punt_lux.protocol.elements.spinner import SpinnerElement
from punt_lux.protocol.elements.table import (
    TableDetail,
    TableElement,
    TableFilter,
    register_codecs as _register_table,
)
from punt_lux.protocol.elements.text import TextElement

__all__ = [
    "ButtonElement",
    "CheckboxElement",
    "CollapsingHeaderElement",
    "ColorPickerElement",
    "ComboElement",
    "DrawElement",
    "Element",
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
    "element_from_dict",
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


# Module-level dispatch codec, populated at import time.  Tests that need
# isolation construct their own ElementCodec instance directly via the
# codec sub-module.
_codec = ElementCodec()
BasicsRegistry().apply(_codec.register)
_register_inputs(_codec.register)
_register_layout(_codec.register)
_register_graphics(_codec.register)
_register_table(_codec.register)


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    result = _codec.to_dict(elem)
    # ``tooltip`` is part of the Element Protocol — every conforming class
    # has it, so we read the attribute directly instead of via ``getattr``
    # (PY-TS-10: no ``hasattr``-equivalent dispatch).
    if elem.tooltip is not None:
        result["tooltip"] = elem.tooltip
    return result


def element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    return _element_to_dict(elem)


def element_from_dict(d: dict[str, Any]) -> Element:
    """Deserialize a dict to the appropriate Element dataclass."""
    elem = _codec.from_dict(d)
    tooltip = d.get("tooltip")
    if tooltip is not None:
        # Every Element subtype declares ``tooltip: str | None`` — the
        # Protocol guarantee makes ``replace(elem, tooltip=...)`` safe.
        elem = replace(elem, tooltip=tooltip)
    return elem


# Inject the package-level recursion functions into layout codecs.  Container
# elements (Group, Window, TabBar, …) call back into the dispatcher; layout.py
# cannot import them eagerly because the aggregator depends on layout.py.
layout.install_dispatchers(_element_to_dict, element_from_dict)
