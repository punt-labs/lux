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

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from punt_lux.protocol.elements import layout

# _strip_none is re-exported for protocol.messages.scene; it lives in basics
# because both basics codecs and the message codecs use it.
from punt_lux.protocol.elements.basics import (
    ImageElement,
    MarkdownElement,
    ProgressElement,
    SeparatorElement,
    SpinnerElement,
    TextElement,
    _strip_none as _strip_none,
    register_codecs as _register_basics,
)
from punt_lux.protocol.elements.codec import ElementCodec
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


def _register_legacy_family(
    serializers: dict[type, Callable[..., dict[str, Any]]],
    deserializers: dict[str, Callable[[dict[str, Any]], Any]],
) -> None:
    """Register a family that still exposes old-style SERIALIZERS/DESERIALIZERS.

    Bridges per-family dispatch tables into ``_codec`` while the families
    are migrated to ``register_codecs`` one at a time.  Removed once every
    family exposes ``register_codecs``.
    """
    for cls, ser in serializers.items():
        # Each Element subtype carries its wire ``kind`` as a Literal default.
        # ``__dataclass_fields__`` is dynamic; reach via ``Any`` to avoid
        # tripping mypy's ``type`` attribute check.
        cls_any: Any = cls
        kind = cls_any.__dataclass_fields__["kind"].default
        if not isinstance(kind, str):
            msg = f"{cls.__name__} has non-string kind default"
            raise TypeError(msg)
        _codec.register(kind, cls, ser, deserializers[kind])


_register_basics(_codec.register)
_register_legacy_family(_INPUTS_SERIALIZERS, _INPUTS_DESERIALIZERS)
_register_legacy_family(_LAYOUT_SERIALIZERS, _LAYOUT_DESERIALIZERS)
_register_legacy_family(_GRAPHICS_SERIALIZERS, _GRAPHICS_DESERIALIZERS)
_register_legacy_family(_TABLE_SERIALIZERS, _TABLE_DESERIALIZERS)


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    result = _codec.to_dict(elem)
    tooltip = getattr(elem, "tooltip", None)
    if tooltip is not None:
        result["tooltip"] = tooltip
    return result


def element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    return _element_to_dict(elem)


def element_from_dict(d: dict[str, Any]) -> Element:
    """Deserialize a dict to the appropriate Element dataclass.

    Accepts dicts matching this module's element schema or as supplied by
    MCP tool callers.  Missing ``content``/``label`` keys default to ``""``.
    """
    elem = _codec.from_dict(d)
    tooltip = d.get("tooltip")
    if tooltip is not None:
        # Invariant: every Element subtype declares tooltip: str | None = None.
        # New element types must include this field or element_from_dict will raise.
        elem = replace(elem, tooltip=tooltip)
    return elem


# Inject the package-level recursion functions into layout codecs.  Container
# elements (Group, Window, TabBar, …) call back into the dispatcher; layout.py
# cannot import them eagerly because the aggregator depends on layout.py.
layout.install_dispatchers(_element_to_dict, element_from_dict)
