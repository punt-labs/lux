"""JsonElementFactory — top-level wire decoder dispatching by ``kind``.

The inbound dispatcher: one instance per tier, constructed at startup with
that tier's ``RendererFactory`` + ``Emit`` + ``PublishSink``. Each
``element_from_dict(raw)`` call routes ``raw["kind"]`` to its per-kind ABC
decoder; the remaining dataclass kinds dispatch through the legacy
``ElementCodec`` table.

The ``publish_sink`` is REQUIRED — without it the Dialog child decoders
would silently swallow ``publish`` decorators and the Button child decoder
would silently drop catalog handlers, both wire-path silent failures.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Self

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonDecoder
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.checkbox_codec import JsonCheckboxDecoder
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.collapsing_header_codec import (
    JsonCollapsingHeaderDecoder,
)
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogDecoder
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.protocol.elements.progress_codec import JsonProgressDecoder
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.tab_bar_codec import JsonTabBarDecoder
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder
from punt_lux.protocol.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)
from punt_lux.protocol.standalone_checkbox_handler import (
    build_standalone_checkbox_handler_decoder,
)
from punt_lux.protocol.standalone_collapsing_header_handler import (
    build_standalone_collapsing_header_handler_decoder,
)
from punt_lux.protocol.standalone_tab_bar_handler import (
    build_standalone_tab_bar_handler_decoder,
)
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.protocol.elements.codec import ElementCodec
    from punt_lux.protocol.renderer import Emit, RendererFactory

    type KindDecoder = Callable[[Mapping[str, object]], AbcElement]

__all__ = ["JsonElementFactory"]

_ABC_KINDS = frozenset({"text", "button", "checkbox", "dialog", "progress"})


class JsonElementFactory:
    """Dispatch wire dicts to per-kind decoders by their ``kind`` field.

    ``element_from_dict(d)`` is the single entry point: it validates
    ``kind`` at the boundary, then routes to either the per-kind ABC
    decoder or the shared codec for the remaining dataclass kinds. The
    decoders are built once with the tier's injected DI and reused on
    every call, so a single instance handles the hot decode path without
    per-call allocation.
    """

    _rf: RendererFactory
    _emit: Emit
    _sink: PublishSink
    _codec: ElementCodec
    _decoders: dict[str, KindDecoder]
    _group_decoder: JsonGroupDecoder
    _collapsing_header_decoder: JsonCollapsingHeaderDecoder
    _tab_bar_decoder: JsonTabBarDecoder

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
        # Per-kind ABC decoders, keyed by wire ``kind`` — one bound ``decode``
        # each. Button carries handler sugar canonicalized before dispatch.
        self._decoders = {
            "text": JsonTextDecoder(
                renderer_factory=renderer_factory, emit=emit, element_cls=TextElement
            ).decode,
            "button": JsonButtonDecoder(
                renderer_factory=renderer_factory,
                emit=emit,
                element_cls=ButtonElement,
                handler_decoder=build_standalone_button_handler_decoder(publish_sink),
            ).decode,
            "checkbox": JsonCheckboxDecoder(
                renderer_factory=renderer_factory,
                emit=emit,
                element_cls=CheckboxElement,
                handler_decoder=build_standalone_checkbox_handler_decoder(publish_sink),
            ).decode,
            "dialog": JsonDialogDecoder(
                renderer_factory=renderer_factory,
                emit=emit,
                element_cls=DialogElement,
                publish_sink=publish_sink,
            ).decode,
            "progress": JsonProgressDecoder(
                renderer_factory=renderer_factory,
                emit=emit,
                element_cls=ProgressElement,
            ).decode,
        }
        # The group decoder recurses each child through this factory's own
        # ``element_from_dict`` so a nested all-ABC group decodes to ABC
        # children exactly as a top-level group would.
        self._group_decoder = JsonGroupDecoder(
            decode_element=self.element_from_dict,
            element_cls=GroupElement,
        )
        # The collapsing-header decoder recurses children through this
        # factory's ``element_from_dict`` (like the group decoder) and wires
        # the tier's publish sink so a wire ``publish`` handler reaches it.
        self._collapsing_header_decoder = JsonCollapsingHeaderDecoder(
            decode_element=self.element_from_dict,
            element_cls=CollapsingHeaderElement,
            handler_decoder=build_standalone_collapsing_header_handler_decoder(
                publish_sink
            ),
        )
        # The tab-bar decoder recurses tab children through ``element_from_dict``
        # and wires the tier's publish sink for a wire ``publish`` handler.
        self._tab_bar_decoder = JsonTabBarDecoder(
            decode_element=self.element_from_dict,
            element_cls=TabBarElement,
            handler_decoder=build_standalone_tab_bar_handler_decoder(publish_sink),
        )
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> AbcElement:
        """Dispatch by ``raw["kind"]`` to the per-kind ABC decoder."""
        kind = raw.get("kind")
        decoder = self._decoders.get(kind) if isinstance(kind, str) else None
        if decoder is None:
            msg = f"JsonElementFactory has no decoder for kind={kind!r}"
            raise ValueError(msg)
        if kind == "button":
            raw = self.canonicalize_button_sugar(raw)
        return decoder(raw)

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

        ABC kinds route through their per-kind decoders; the remaining
        dataclass kinds continue through the ``ElementCodec`` table. A
        missing, empty, or non-string ``kind`` raises ``ValueError``.
        """
        kind = d.get("kind")
        if not isinstance(kind, str) or not kind:
            msg = "Element missing or invalid 'kind' field"
            raise ValueError(msg)
        if kind in _ABC_KINDS:
            return self._decode_abc_leaf(kind, d)
        return self._decode_container_or_legacy(kind, d)

    def _decode_abc_leaf(self, kind: str, d: dict[str, Any]) -> Any:
        """Decode a migrated leaf kind through its per-kind ABC decoder."""
        abc_elem = self.decode(d)
        if isinstance(
            abc_elem,
            TextElement
            | ButtonElement
            | CheckboxElement
            | DialogElement
            | ProgressElement,
        ):
            return abc_elem
        msg = f"JsonElementFactory returned unexpected type for kind={kind!r}"
        raise AssertionError(msg)

    def _decode_container_or_legacy(self, kind: str, d: dict[str, Any]) -> Any:
        """Fork a conditionally-ABC container onto the ABC path, else legacy.

        A ``group`` or ``collapsing_header`` whose entire subtree is
        migrated-ABC decodes onto its ABC class; any legacy descendant (or a
        paged group) forks the whole subtree legacy.
        """
        if kind == "group" and JsonGroupDecoder.is_all_abc(d):
            return self._group_decoder.decode(d)
        if kind == "collapsing_header" and ContainerAbcGate.is_all_abc(d):
            return self._collapsing_header_decoder.decode(d)
        if kind == "tab_bar" and ContainerAbcGate.is_all_abc(d):
            return self._tab_bar_decoder.decode(d)
        return self._decode_legacy(d)

    def _decode_legacy(self, d: dict[str, Any]) -> Any:
        """Decode a dataclass kind through the codec, validating tooltip.

        The codec returns each Element with its declared tooltip default
        (``None``); the cross-element tooltip read here validates the wire
        value at the boundary (PY-EH-1) so a non-str never reaches a
        renderer via ``dataclasses.replace``.
        """
        elem = self._codec.from_dict(d)
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
            | GroupElement
            | CollapsingHeaderElement
            | TabBarElement
            | ProgressElement,
        ):
            msg = f"kind {elem.kind!r} must route through ABC decoder"
            raise AssertionError(msg)
        return replace(elem, tooltip=tooltip)

    @property
    def codec(self) -> ElementCodec:
        """Return the element codec table this factory uses for non-ABC kinds."""
        return self._codec
