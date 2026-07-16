"""JsonElementFactory — top-level wire decoder dispatching by ``kind``.

The inbound dispatcher: one instance per tier, constructed at startup with
that tier's ``RendererFactory`` + ``Emit`` + ``PublishSink``. Its per-kind
decoders are built from the shared ``AbcElementRegistry`` — migrating a kind
adds a spec to the registration table, never an arm here. The remaining
dataclass kinds dispatch through the legacy ``ElementCodec`` table.

The ``publish_sink`` is REQUIRED — without it the Dialog child decoders would
silently swallow ``publish`` decorators and the Button child decoder would
silently drop catalog handlers, both wire-path silent failures.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.protocol.elements.abc_kind_spec import TierBinding
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element as AbcElement
    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.protocol.elements.abc_kind_spec import KindDecoder
    from punt_lux.protocol.elements.abc_registry import AbcElementRegistry
    from punt_lux.protocol.elements.codec import ElementCodec
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonElementFactory"]


class JsonElementFactory:
    """Dispatch wire dicts to per-kind decoders by their ``kind`` field.

    ``element_from_dict(d)`` is the single entry point: it validates ``kind``
    at the boundary, then routes to either the per-kind ABC decoder (built from
    the ``AbcElementRegistry``) or the shared codec for the remaining dataclass
    kinds. The decoders are built once with the tier's injected DI and reused on
    every call, so a single instance handles the hot decode path without
    per-call allocation.
    """

    _codec: ElementCodec
    _registry: AbcElementRegistry
    _decoders: dict[str, KindDecoder]
    _leaf_kinds: frozenset[str]
    _container_kinds: frozenset[str]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        publish_sink: PublishSink,
        codec: ElementCodec,
    ) -> Self:
        self = super().__new__(cls)
        self._codec = codec
        self._registry = DEFAULT_ABC_REGISTRY
        # Each container decoder recurses its children through this factory's
        # own ``element_from_dict`` so a nested all-ABC container decodes to ABC
        # children exactly as a top-level one would. Button carries handler
        # sugar its registered decoder canonicalizes before dispatch.
        binding = TierBinding(
            renderer_factory=renderer_factory,
            emit=emit,
            publish_sink=publish_sink,
            recurse=self.element_from_dict,
        )
        self._decoders = self._registry.build_decoders(binding)
        self._leaf_kinds = self._registry.leaf_kinds
        self._container_kinds = self._registry.container_kinds
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> AbcElement:
        """Dispatch by ``raw["kind"]`` to the per-kind ABC decoder."""
        kind = raw.get("kind")
        decoder = self._decoders.get(kind) if isinstance(kind, str) else None
        if decoder is None:
            msg = f"JsonElementFactory has no decoder for kind={kind!r}"
            raise ValueError(msg)
        return decoder(raw)

    def element_from_dict(self, d: dict[str, Any]) -> Any:
        """Deserialize a wire dict to the appropriate Element class.

        Leaf ABC kinds route through their per-kind decoders; an all-ABC
        container forks onto its ABC class; the remaining dataclass kinds
        continue through the ``ElementCodec`` table. A missing, empty, or
        non-string ``kind`` raises ``ValueError``.
        """
        kind = d.get("kind")
        if not isinstance(kind, str) or not kind:
            msg = "Element missing or invalid 'kind' field"
            raise ValueError(msg)
        if kind in self._leaf_kinds:
            return self.decode(d)
        if kind in self._container_kinds and ContainerAbcGate.is_all_abc(d):
            return self._decoders[kind](d)
        return self._decode_legacy(d)

    def _decode_legacy(self, d: dict[str, Any]) -> Any:
        """Decode a dataclass kind through the codec, validating tooltip.

        The codec returns each Element with its declared tooltip default
        (``None``); the cross-element tooltip read here validates the wire
        value at the boundary (PY-EH-1) so a non-str never reaches a renderer
        via ``dataclasses.replace``.
        """
        elem = self._codec.from_dict(d)
        tooltip_ctx = ElementWireContext.for_kind(elem.kind)
        tooltip = tooltip_ctx.optional_nullable_str(d, "tooltip")
        if tooltip is None:
            return elem
        if isinstance(elem, self._registry.abc_types):  # pragma: no cover
            msg = f"kind {elem.kind!r} must route through ABC decoder"
            raise AssertionError(msg)
        # ``elem`` here is a legacy dataclass kind — the guard above rejects any
        # ABC instance (a legacy-forked container decodes to its ``Legacy*``
        # class, not the ABC one). mypy cannot narrow through the runtime
        # ``abc_types`` tuple, so ``replace``'s dataclass target is cast.
        return replace(cast("Any", elem), tooltip=tooltip)

    @property
    def codec(self) -> ElementCodec:
        """Return the element codec table this factory uses for non-ABC kinds."""
        return self._codec
