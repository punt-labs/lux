"""JsonElementFactory — top-level wire decoder dispatching by ``kind``.

The io-model inbound dispatcher. One instance per tier (constructed at
startup with that tier's ``RendererFactory`` + ``Emit`` + ``PublishSink``);
each ``element_from_dict(raw)`` call routes to the per-kind decoder for
``raw["kind"]``. ABC-shaped kinds (Text, Button, Dialog) flow through
io-model per-kind decoders; the remaining dataclass kinds dispatch
through the legacy ``ElementCodec`` table.

The ``publish_sink`` is REQUIRED. A factory has no permission to be
constructed without one — its Dialog child decoders would silently
swallow ``publish`` decorators, and its Button child decoder would
silently drop catalog handlers. Both are wire-path silent failures the
directive bans.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Self

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonDecoder
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogDecoder
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder
from punt_lux.protocol.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.protocol.elements.codec import ElementCodec
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonElementFactory"]

_log = logging.getLogger(__name__)

_ABC_KINDS = frozenset({"text", "button", "dialog"})


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
    _display_send: Callable[[Any], None] | None
    _text_decoder: JsonTextDecoder
    _button_decoder: JsonButtonDecoder
    _dialog_decoder: JsonDialogDecoder

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        publish_sink: PublishSink,
        codec: ElementCodec,
        display_send: Callable[[Any], None] | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._sink = publish_sink
        self._codec = codec
        self._display_send = display_send
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
        self._dialog_decoder = JsonDialogDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=DialogElement,
            publish_sink=publish_sink,
        )
        return self

    def decode(self, raw: Mapping[str, object]) -> AbcElement:
        """Dispatch by ``raw["kind"]`` to the per-kind ABC decoder."""
        kind = raw.get("kind")
        if kind == "text":
            return self._text_decoder.decode(raw)
        if kind == "button":
            raw = self._canonicalize_top_level_publish(raw)
            elem = self._button_decoder.decode(raw)
            self._install_remote_dispatch(elem)
            return elem
        if kind == "dialog":
            elem = self._dialog_decoder.decode(raw)
            self._install_remote_dispatch_on_children(elem)
            return elem
        msg = f"JsonElementFactory has no decoder for kind={kind!r}"
        raise ValueError(msg)

    @staticmethod
    def _canonicalize_top_level_publish(
        raw: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Promote top-level ``publish`` sugar to a ``handlers`` entry.

        Wire sugar: ``{"kind": "button", "publish": ["topic1"]}``
        Canonical:  ``{"kind": "button", "handlers": [{"event": "click",
                       "factory": "noop", "wrap": [{"decorator": "publish",
                       "topics": ["topic1"]}]}]}``

        If the raw dict already has a ``handlers`` key, returns unchanged.
        """
        publish = raw.get("publish")
        if publish is None or "handlers" in raw:
            return raw
        handler_spec: dict[str, object] = {
            "event": "click",
            "factory": "noop",
            "wrap": [{"decorator": "publish", "topics": publish}],
        }
        merged = dict(raw)
        merged["handlers"] = [handler_spec]
        del merged["publish"]
        return merged

    def _install_remote_dispatch(self, elem: AbcElement) -> None:
        """Install a remote_dispatch handler if this factory is display-side."""
        if self._display_send is None:
            return
        from punt_lux.domain.display_interaction import DisplayInteraction
        from punt_lux.domain.handlers.remote_dispatch import remote_dispatch

        action = getattr(elem, "action", None) or elem.id
        _log.debug(
            "install remote_dispatch element_id=%s action=%s event=DisplayInteraction",
            elem.id,
            action,
        )
        elem.add_handler(
            DisplayInteraction,
            remote_dispatch(self._display_send, elem.id, action),
        )

    def _install_remote_dispatch_on_children(self, elem: AbcElement) -> None:
        """Install remote_dispatch on a composite's children recursively."""
        if self._display_send is None:
            return
        from punt_lux.domain.composite import Composite

        if isinstance(elem, Composite):
            for child in elem.children:
                if isinstance(child, AbcElement):
                    self._install_remote_dispatch(child)

    def element_from_dict(self, d: dict[str, Any]) -> Any:
        """Deserialize a wire dict to the appropriate Element class.

        Text, Button, and Dialog route through the io-model per-kind
        decoders; the remaining dataclass kinds continue through the
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
            if isinstance(abc_elem, TextElement | ButtonElement | DialogElement):
                return abc_elem
            msg = f"JsonElementFactory returned unexpected type for kind={kind!r}"
            raise AssertionError(msg)
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
            elem, TextElement | ButtonElement | DialogElement
        ):
            msg = f"kind {elem.kind!r} must route through ABC decoder"
            raise AssertionError(msg)
        return replace(elem, tooltip=tooltip)

    @property
    def codec(self) -> ElementCodec:
        """Return the element codec table this factory uses for non-ABC kinds."""
        return self._codec
