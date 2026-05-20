"""Element protocol package — wire types and serialization dispatch.

Sub-modules house each family of element types together with their codec
helpers:

- ``basics``: static display primitives (Text, Image, Separator, …)
- ``inputs``: interactive controls (Button, Slider, Checkbox, …)
- ``layout``: containers (Group, Window, TabBar, …)
- ``graphics``: 2D canvas and chart (Draw, Plot)
- ``table``: tabular data with filters and detail panels
- ``patch``: single-element update payload

This ``__init__`` is the package surface: it re-exports every public name,
assembles the ``Element`` union from per-family contributions, and provides
the ``element_to_dict`` / ``element_from_dict`` dispatchers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from punt_lux.protocol.elements import layout

# _strip_none is re-exported for protocol.messages.scene; it lives in basics
# because both basics codecs and the message codecs use it.
from punt_lux.protocol.elements.basics import (
    DESERIALIZERS as _BASICS_DESERIALIZERS,
    SERIALIZERS as _BASICS_SERIALIZERS,
    ImageElement,
    MarkdownElement,
    ProgressElement,
    SeparatorElement,
    SpinnerElement,
    TextElement,
    _strip_none as _strip_none,
)
from punt_lux.protocol.elements.graphics import (
    DESERIALIZERS as _GRAPHICS_DESERIALIZERS,
    SERIALIZERS as _GRAPHICS_SERIALIZERS,
    DrawElement,
    PlotElement,
)
from punt_lux.protocol.elements.inputs import (
    DESERIALIZERS as _INPUTS_DESERIALIZERS,
    SERIALIZERS as _INPUTS_SERIALIZERS,
    ButtonElement,
    CheckboxElement,
    ColorPickerElement,
    ComboElement,
    InputNumberElement,
    InputTextElement,
    RadioElement,
    SelectableElement,
    SliderElement,
)
from punt_lux.protocol.elements.layout import (
    DESERIALIZERS as _LAYOUT_DESERIALIZERS,
    SERIALIZERS as _LAYOUT_SERIALIZERS,
    CollapsingHeaderElement,
    GroupElement,
    ModalElement,
    TabBarElement,
    TreeElement,
    WindowElement,
)

# _patch_to_dict / _patch_from_dict are re-exported for protocol.messages.scene
# (used by UpdateMessage codec).
from punt_lux.protocol.elements.patch import (
    Patch,
    _patch_from_dict as _patch_from_dict,
    _patch_to_dict as _patch_to_dict,
)
from punt_lux.protocol.elements.table import (
    DESERIALIZERS as _TABLE_DESERIALIZERS,
    SERIALIZERS as _TABLE_SERIALIZERS,
    TableDetail,
    TableElement,
    TableFilter,
)

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


_ELEMENT_SERIALIZERS: dict[type, Callable[..., dict[str, Any]]] = {
    **_BASICS_SERIALIZERS,
    **_INPUTS_SERIALIZERS,
    **_LAYOUT_SERIALIZERS,
    **_GRAPHICS_SERIALIZERS,
    **_TABLE_SERIALIZERS,
}


_ELEMENT_DESERIALIZERS: dict[str, Callable[[dict[str, Any]], Element]] = {
    **_BASICS_DESERIALIZERS,
    **_INPUTS_DESERIALIZERS,
    **_LAYOUT_DESERIALIZERS,
    **_GRAPHICS_DESERIALIZERS,
    **_TABLE_DESERIALIZERS,
}


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    serializer = _ELEMENT_SERIALIZERS.get(type(elem))
    if serializer is not None:
        result: dict[str, Any] = serializer(elem)
        tooltip = getattr(elem, "tooltip", None)
        if tooltip is not None:
            result["tooltip"] = tooltip
        return result
    msg = f"Unknown element type: {type(elem)}"
    raise TypeError(msg)


def element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    return _element_to_dict(elem)


def element_from_dict(d: dict[str, Any]) -> Element:
    """Deserialize a dict to the appropriate Element dataclass.

    Accepts dicts matching this module's element schema or as supplied by
    MCP tool callers.  Missing ``content``/``label`` keys default to ``""``.
    """
    kind = d.get("kind", "text")
    deserializer = _ELEMENT_DESERIALIZERS.get(kind)
    if deserializer is not None:
        elem = deserializer(d)
        tooltip = d.get("tooltip")
        if tooltip is not None:
            # Invariant: every Element subtype declares tooltip: str | None = None.
            # New element types must include this field or element_from_dict will raise.
            elem = replace(elem, tooltip=tooltip)
        return elem
    msg = f"Unknown element kind: {kind!r}"
    raise ValueError(msg)


# Inject the package-level recursion functions into layout codecs.  Container
# elements (Group, Window, TabBar, …) call back into the dispatcher; layout.py
# cannot import them eagerly because the aggregator depends on layout.py.
layout.install_dispatchers(_element_to_dict, element_from_dict)


# _element_to_dict, _patch_from_dict, _patch_to_dict, and _strip_none are
# imported above with explicit ``as`` aliases so ruff knows they are
# intentional re-exports.  They remain private (not in __all__) but stay
# importable as ``from punt_lux.protocol.elements import _xxx`` for the
# message codecs in protocol/messages.py.  See the phase-A design doc.
