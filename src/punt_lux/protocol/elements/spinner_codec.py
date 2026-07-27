"""JsonSpinnerDecoder + JsonSpinnerEncoder — wire codec for ``SpinnerElement``.

The codec body lives in this sibling module rather than on
``SpinnerElement``. ``SpinnerElement.to_dict`` / ``SpinnerElement.from_dict``
remain as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at
construction — off the display tier that is the fail-loud sentinel, which
the Display rebinds post-receive. This encoder/decoder owns ``tooltip``
directly as its own wire field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.spinner import SpinnerElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonSpinnerDecoder", "JsonSpinnerEncoder"]


class JsonSpinnerDecoder:
    """Decode a wire dict to a fully-constructed ``SpinnerElement``.

    Constructed once per tier with that tier's ``renderer_factory`` +
    ``emit``; every decoded element is born with the same injected DI.
    Boundary validation (PY-EH-1) routes through ``ElementWireContext`` so a
    non-numeric ``radius`` or non-string ``id`` raises a typed ``ValueError``
    with the offending field named in the message.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[SpinnerElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[SpinnerElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> SpinnerElement:
        """Construct a SpinnerElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("spinner")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_id(raw),
            label=ctx.optional_str(raw, "label", default=""),
            radius=ctx.optional_number(raw, "radius", default=16.0),
            color=ctx.optional_str(raw, "color", default="#3399FF"),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonSpinnerEncoder:
    """Encode a ``SpinnerElement`` to its JSON-compatible wire dict.

    Stateless. ``radius`` and ``color`` are always emitted; ``label`` and
    ``tooltip`` are omitted when absent.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: SpinnerElement) -> dict[str, object]:
        """Serialize a SpinnerElement to a JSON-compatible dict."""
        # ``label`` "" sentinel flattens to None so strip_none drops it.
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "radius": elem.radius,
                "color": elem.color,
                "label": elem.label or None,
                "tooltip": elem.tooltip,
            }
        )
