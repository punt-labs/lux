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

from punt_lux.protocol.element_factory import JsonElementFactory
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
from punt_lux.protocol.elements.element_wire import ElementWireContext
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
from punt_lux.protocol.renderers.null import NullRendererFactory

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
InputsRegistry().apply(_codec.register)
_register_layout(_codec.register)
_register_graphics(_codec.register)
_register_table(_codec.register)

# io-model dispatch — Text-only in PR 3 (per pr3-v2.1-design.md §3).
# The factory is constructed with Hub-tier defaults (NullRendererFactory +
# no-op emit); production tiers construct their own with the real DI at
# startup. The module-level instance covers the existing test/agent path
# that reaches ``element_from_dict`` without explicit DI.


def _no_op_emit(_msg: object) -> None:
    """Module-level sentinel emit channel (PY-DP-9 Null Object)."""


_ELEMENT_FACTORY = JsonElementFactory(
    renderer_factory=NullRendererFactory(),
    emit=_no_op_emit,
)
_ENCODER_FACTORY = JsonEncoderFactory()


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    if isinstance(elem, TextElement):
        result = _ENCODER_FACTORY.encode(elem)
    else:
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
    """Deserialize a dict to the appropriate Element class.

    Text routes through ``JsonElementFactory`` (io-model path —
    pr3-v2.1-design.md §3); the other 23 kinds continue through the
    PR-2 ``ElementCodec``. A missing, empty, or non-string ``kind`` is a
    ``ValueError`` — mirrors ``ElementCodec.from_dict``'s contract so
    every element path has the same boundary semantics.
    """
    kind = d.get("kind")
    if not isinstance(kind, str) or not kind:
        msg = "Element missing or invalid 'kind' field"
        raise ValueError(msg)
    if kind == "text":
        # ``JsonTextDecoder`` already pulls and validates ``tooltip`` from
        # the wire dict (via ``optional_nullable_str``) — its decoded
        # element carries the canonical tooltip.  Re-applying the read
        # here via ``apply_patch`` was a redundant second pass (CR1) so
        # the ABC branch short-circuits.  The decoder still raises a
        # typed ``ValueError`` on a non-string tooltip — the boundary
        # validation contract is preserved.
        return _ELEMENT_FACTORY.decode(d)
    elem: Element = _codec.from_dict(d)
    # Copilot CP-5: validate tooltip at the boundary (PY-EH-1).  The
    # codec returns each Element with its declared tooltip default
    # (``None``); the cross-element tooltip read here previously trusted
    # whatever value the wire carried and forwarded non-str into
    # renderers via ``dataclasses.replace``.  Route the read through
    # ``ElementWireContext.optional_nullable_str`` so explicit null is
    # tolerated and any other non-str raises a typed ``ValueError``.
    tooltip_ctx = ElementWireContext.for_kind(elem.kind)
    tooltip = tooltip_ctx.optional_nullable_str(d, "tooltip")
    if tooltip is None:
        return elem
    # The text branch returned above; ``_codec`` carries only the 23
    # dataclass-shaped kinds, so the union here excludes ``TextElement``.
    # The ``isinstance`` guard narrows the union for ``replace`` (whose
    # type variable cannot bind to the ABC-shaped ``TextElement``) and
    # documents the dispatch invariant.
    if isinstance(elem, TextElement):  # pragma: no cover - dispatch invariant
        msg = "text kind must route through _ELEMENT_FACTORY"
        raise AssertionError(msg)
    # Every dataclass Element subtype declares ``tooltip: str | None`` —
    # the Protocol guarantee makes ``replace(elem, tooltip=...)`` safe.
    return replace(elem, tooltip=tooltip)


# Inject the package-level recursion functions into layout codecs.  Container
# elements (Group, Window, TabBar, …) call back into the dispatcher; layout.py
# cannot import them eagerly because the aggregator depends on layout.py.
layout.install_dispatchers(_element_to_dict, element_from_dict)
