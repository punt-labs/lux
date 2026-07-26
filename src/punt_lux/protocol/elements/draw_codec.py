"""JsonDrawDecoder + JsonDrawEncoder — wire codec for ``DrawElement``.

The codec body lives in this sibling module rather than on ``DrawElement``.
``DrawElement.to_dict`` / ``DrawElement.from_dict`` remain short delegators so
the runtime-checkable ``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at construction;
off the display tier that is the fail-loud sentinel, which the Display rebinds
post-receive. Commands decode through ``DrawCommandDecoder.decode_all``, so a
malformed command raises ``ValueError`` at the boundary — the invalid canvas
never reaches the display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.draw_decoder import DrawCommandDecoder
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.draw import DrawElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonDrawDecoder", "JsonDrawEncoder"]


class JsonDrawDecoder:
    """Decode a wire dict to a fully-constructed ``DrawElement``.

    Constructed once per tier with that tier's ``renderer_factory`` + ``emit``;
    every decoded element is born with the same injected DI. Boundary validation
    (PY-EH-1) routes through ``ElementWireContext`` and
    ``DrawCommandDecoder.decode_all`` so a non-int size or a malformed command
    raises a typed ``ValueError``.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[DrawElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[DrawElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> DrawElement:
        """Construct a DrawElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("draw")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_id(raw),
            width=ctx.optional_int_with_default(raw, "width", default=400),
            height=ctx.optional_int_with_default(raw, "height", default=300),
            bg_color=ctx.optional_nullable_str(raw, "bg_color"),
            commands=DrawCommandDecoder.default().decode_all(
                raw.get("commands", ()), "commands"
            ),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonDrawEncoder:
    """Encode a ``DrawElement`` to its JSON-compatible wire dict.

    Stateless. ``bg_color`` and ``tooltip`` are omitted when absent; the
    remaining fields are always emitted so the wire shape matches the legacy
    dataclass codec.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: DrawElement) -> dict[str, object]:
        """Serialize a DrawElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "width": elem.width,
                "height": elem.height,
                "bg_color": elem.bg_color,
                "commands": [cmd.to_dict() for cmd in elem.commands],
                "tooltip": elem.tooltip,
            }
        )
