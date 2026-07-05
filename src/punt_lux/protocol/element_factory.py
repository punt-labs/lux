"""JsonElementFactory — top-level wire decoder dispatching by ``kind``.

The inbound dispatcher. One instance per tier (constructed at startup
with that tier's ``RendererFactory`` + ``Emit`` + ``PublishSink``); each
``element_from_dict(raw)`` call routes to the per-kind decoder for
``raw["kind"]``. ABC-shaped kinds (Text, Button, Dialog) flow through
per-kind decoders; the remaining dataclass kinds dispatch through the
legacy ``ElementCodec`` table.

The ``publish_sink`` is REQUIRED. A factory has no permission to be
constructed without one — its Dialog child decoders would silently
swallow ``publish`` decorators, and its Button child decoder would
silently drop catalog handlers. Both are wire-path silent failures the
directive bans.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Self

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonDecoder
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.checkbox_codec import JsonCheckboxDecoder
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogDecoder
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder
from punt_lux.protocol.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)
from punt_lux.protocol.standalone_checkbox_handler import (
    build_standalone_checkbox_handler_decoder,
)
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.protocol.elements.codec import ElementCodec
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonElementFactory"]

_ABC_KINDS = frozenset({"text", "button", "checkbox", "dialog"})


class JsonElementFactory:
    """Dispatch wire dicts to per-kind decoders by their ``kind`` field.

    Holds the tier's ``RendererFactory`` + ``Emit`` + ``PublishSink`` so
    every decoded element is born with the same injected DI.
    ``element_from_dict(d)`` is the single entry point — it validates
    ``kind`` at the boundary, then routes to either the ABC-shaped
    per-kind decoder (Text, Button, Dialog) or the shared element
    codec for the remaining dataclass kinds.

    Per-kind decoders are constructed once and reused across every
    ``element_from_dict()`` call — the decoders carry only injected DI,
    so a single instance handles every wire dict for that kind without
    per-call allocation on the hot decode path.
    """

    _rf: RendererFactory
    _emit: Emit
    _sink: PublishSink
    _codec: ElementCodec
    _text_decoder: JsonTextDecoder
    _button_decoder: JsonButtonDecoder
    _checkbox_decoder: JsonCheckboxDecoder
    _dialog_decoder: JsonDialogDecoder
    _group_decoder: JsonGroupDecoder

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        publish_sink: PublishSink,
        codec: ElementCodec,
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._sink = publish_sink
        self._codec = codec
        self._text_decoder = JsonTextDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=TextElement,
        )
        self._button_decoder = JsonButtonDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=ButtonElement,
            handler_decoder=build_standalone_button_handler_decoder(publish_sink),
        )
        self._checkbox_decoder = JsonCheckboxDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=CheckboxElement,
            handler_decoder=build_standalone_checkbox_handler_decoder(publish_sink),
        )
        self._dialog_decoder = JsonDialogDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=DialogElement,
            publish_sink=publish_sink,
        )
        # The group decoder recurses each child through this factory's own
        # ``element_from_dict`` so a nested all-ABC group decodes to ABC
        # children exactly as a top-level group would.
        self._group_decoder = JsonGroupDecoder(
            decode_element=self.element_from_dict,
            element_cls=GroupElement,
        )
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> AbcElement:
        """Dispatch by ``raw["kind"]`` to the per-kind ABC decoder."""
        kind = raw.get("kind")
        if kind == "text":
            return self._text_decoder.decode(raw)
        if kind == "button":
            raw = self.canonicalize_button_sugar(raw)
            return self._button_decoder.decode(raw)
        if kind == "checkbox":
            return self._checkbox_decoder.decode(raw)
        if kind == "dialog":
            return self._dialog_decoder.decode(raw)
        msg = f"JsonElementFactory has no decoder for kind={kind!r}"
        raise ValueError(msg)

    @staticmethod
    def canonicalize_button_sugar(
        raw: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Promote top-level ``click`` and ``publish`` sugar to ``handlers``.

        Wire sugar examples:
          ``{"click": "confirm", "publish": ["topic"]}``
          ``{"publish": ["topic"]}``  (no click verb → noop factory)
          ``{"click": "cancel"}``     (no publish → no decorator)

        If the raw dict already has a ``handlers`` key, returns unchanged.
        """
        click = raw.get("click")
        publish = raw.get("publish")
        if click is None and publish is None:
            return raw
        if "handlers" in raw:
            return raw
        factory = "call_model" if click else "noop"
        params: dict[str, object] = {}
        if click:
            params["verb"] = click
        wrap: list[dict[str, object]] = []
        if publish:
            wrap.append({"decorator": "publish", "topics": publish})
        handler_spec: dict[str, object] = {
            "event": "click",
            "factory": factory,
            **params,
            "wrap": wrap,
        }
        merged = dict(raw)
        merged["handlers"] = [handler_spec]
        merged.pop("click", None)
        merged.pop("publish", None)
        return merged

    def element_from_dict(self, d: dict[str, Any]) -> Any:
        """Deserialize a wire dict to the appropriate Element class.

        Text, Button, and Dialog route through the per-kind decoders;
        the remaining dataclass kinds continue through the
        ``ElementCodec`` table. A missing, empty, or non-string ``kind``
        is a ``ValueError`` — mirrors ``ElementCodec.from_dict``'s
        contract so every element path has the same boundary semantics.
        """
        kind = d.get("kind")
        if not isinstance(kind, str) or not kind:
            msg = "Element missing or invalid 'kind' field"
            raise ValueError(msg)
        if kind in _ABC_KINDS:
            abc_elem = self.decode(d)
            if isinstance(
                abc_elem, TextElement | ButtonElement | CheckboxElement | DialogElement
            ):
                return abc_elem
            msg = f"JsonElementFactory returned unexpected type for kind={kind!r}"
            raise AssertionError(msg)
        # ``group`` forks by all-ABC-ness: a rows/columns group whose entire
        # subtree is migrated-ABC decodes onto the ABC ``GroupElement``; any
        # legacy descendant or a paged layout falls through to the legacy
        # container below.
        if kind == "group" and JsonGroupDecoder.is_all_abc(d):
            return self._group_decoder.decode(d)
        elem = self._codec.from_dict(d)
        # Validate tooltip at the boundary (PY-EH-1). The codec returns
        # each Element with its declared tooltip default (``None``); the
        # cross-element tooltip read here would otherwise trust whatever
        # value the wire carried and forward non-str into renderers via
        # ``dataclasses.replace``.
        tooltip_ctx = ElementWireContext.for_kind(elem.kind)
        tooltip = tooltip_ctx.optional_nullable_str(d, "tooltip")
        if tooltip is None:
            return elem
        if isinstance(  # pragma: no cover - dispatch invariant
            elem,
            TextElement
            | ButtonElement
            | CheckboxElement
            | DialogElement
            | GroupElement,
        ):
            msg = f"kind {elem.kind!r} must route through ABC decoder"
            raise AssertionError(msg)
        return replace(elem, tooltip=tooltip)

    @property
    def codec(self) -> ElementCodec:
        """Return the element codec table this factory uses for non-ABC kinds."""
        return self._codec
