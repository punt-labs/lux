"""JsonElementFactory — top-level wire decoder dispatching by ``kind``.

The inbound dispatcher: one instance per tier, constructed at startup with
that tier's ``RendererFactory`` + ``Emit`` + ``PublishSink``. Its per-kind
decoders are built from the shared ``AbcElementRegistry`` — every kind decodes
onto its Element-ABC class, and migrating a new kind adds a spec to the
registration table, never an arm here.

The ``publish_sink`` is REQUIRED — without it the Dialog child decoders would
silently swallow ``publish`` decorators and the Button child decoder would
silently drop catalog handlers, both wire-path silent failures.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.protocol.elements.abc_kind_spec import TierBinding
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element as AbcElement
    from punt_lux.domain.handlers.publish_sink import PublishSink
    from punt_lux.protocol.elements.abc_kind_spec import KindDecoder
    from punt_lux.protocol.elements.abc_registry import AbcElementRegistry
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonElementFactory"]


class JsonElementFactory:
    """Dispatch wire dicts to per-kind decoders by their ``kind`` field.

    ``element_from_dict(d)`` is the single entry point: it validates ``kind``
    at the boundary, then routes to the per-kind ABC decoder built from the
    ``AbcElementRegistry``. The decoders are built once with the tier's injected
    DI and reused on every call, so a single instance handles the hot decode
    path without per-call allocation.
    """

    _registry: AbcElementRegistry
    _decoders: dict[str, KindDecoder]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        publish_sink: PublishSink,
    ) -> Self:
        self = super().__new__(cls)
        self._registry = DEFAULT_ABC_REGISTRY
        # Each container decoder recurses its children through this factory's
        # own ``element_from_dict`` so a nested container decodes exactly as a
        # top-level one would. Button carries handler sugar its registered
        # decoder canonicalizes before dispatch.
        binding = TierBinding(
            renderer_factory=renderer_factory,
            emit=emit,
            publish_sink=publish_sink,
            recurse=self.element_from_dict,
        )
        self._decoders = self._registry.build_decoders(binding)
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

    def element_from_dict(self, d: object) -> Any:
        """Deserialize a wire dict to its Element-ABC class.

        Validates the wire shape at the boundary, then dispatches to the per-kind
        decoder (leaf or container); a container recurses its children through
        this same method. A non-mapping wire (a bare ``42`` or list where an
        element belongs) raises ``TypeError``, and a missing, empty, non-string,
        or unknown ``kind`` raises ``ValueError`` — the child decode never reaches
        ``d.get`` on a non-mapping and escapes as an ``AttributeError``.
        """
        if not isinstance(d, Mapping):
            msg = f"element wire must be a mapping, got {type(d).__name__}"
            raise TypeError(msg)
        raw = cast("Mapping[str, object]", d)
        kind = raw.get("kind")
        if not isinstance(kind, str) or not kind:
            msg = "Element missing or invalid 'kind' field"
            raise ValueError(msg)
        return self.decode(raw)
