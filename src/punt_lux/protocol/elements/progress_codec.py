"""JsonProgressDecoder + JsonProgressEncoder — wire codec for ``ProgressElement``.

The codec body lives in this sibling module rather than on
``ProgressElement``. ``ProgressElement.to_dict`` / ``ProgressElement.from_dict``
remain as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at
construction — off the display tier that is the fail-loud sentinel, which
the Display rebinds post-receive. The encoder takes state directly. Unlike
the legacy dataclass codec, this encoder/decoder owns ``tooltip`` directly
(the legacy path relied on a generic replace that ABC kinds never reach).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.progress import ProgressElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonProgressDecoder", "JsonProgressEncoder"]


class JsonProgressDecoder:
    """Decode a wire dict to a fully-constructed ``ProgressElement``.

    Constructed once per tier with that tier's ``renderer_factory`` +
    ``emit``; every decoded element is born with the same injected DI.
    Boundary validation (PY-EH-1) routes through ``ElementWireContext`` so a
    non-numeric ``fraction`` or non-string ``id`` raises a typed ``ValueError``
    with the offending field named in the message.

    The decoder holds a reference to the ``ProgressElement`` class (passed in
    at construction) so this module can be imported by ``progress.py`` without
    circular-import grief; ``progress.py``'s delegators construct a decoder
    with ``cls`` and call ``.decode(d)``.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[ProgressElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[ProgressElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> ProgressElement:
        """Construct a ProgressElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("progress")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            fraction=ctx.require_number(raw, "fraction"),
            label=ctx.optional_str(raw, "label", default=""),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonProgressEncoder:
    """Encode a ``ProgressElement`` to its JSON-compatible wire dict.

    Stateless. ``label`` and ``tooltip`` are omitted when absent so the wire
    shape matches the legacy dataclass codec byte-for-byte; ``fraction`` is
    always emitted.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: ProgressElement) -> dict[str, object]:
        """Serialize a ProgressElement to a JSON-compatible dict."""
        # ``label`` "" sentinel flattens to None so strip_none drops it.
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "fraction": elem.fraction,
                "label": elem.label or None,
                "tooltip": elem.tooltip,
            }
        )
