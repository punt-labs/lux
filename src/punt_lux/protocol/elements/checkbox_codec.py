"""JsonCheckboxDecoder + JsonCheckboxEncoder — wire codec for ``CheckboxElement``.

Per the text/text_codec split pattern: the codec body that used to live
on ``CheckboxElement`` (frozen dataclass) moves into this sibling module.
``CheckboxElement.to_dict`` / ``CheckboxElement.from_dict`` remain as
short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at
construction so the io-model element is born with its DI wired in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.interaction import ValueChanged
    from punt_lux.protocol.elements.checkbox import CheckboxElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonCheckboxDecoder", "JsonCheckboxEncoder"]


class _UpdateValueHandler:
    """Serializable handler that updates a checkbox's value on toggle.

    On the Hub side, this handler runs when ``ValueChanged`` fires —
    updating the authoritative state via ``apply_patch``. On the
    Display side, ``wrap_handlers_for_remote`` wraps it in a
    ``RemoteDispatchGroup`` that sends the interaction to the Hub.
    """

    _elem: CheckboxElement

    def __new__(cls, elem: CheckboxElement) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (object.__new__, (type(self),), {"_elem": self._elem})

    def __setstate__(self, state: dict[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @trace
    def __call__(self, event: ValueChanged) -> None:
        self._elem.apply_patch({"value": event.value})


class JsonCheckboxDecoder:
    """Decode a wire dict to a fully-constructed ``CheckboxElement``.

    Constructed once per tier with that tier's ``renderer_factory`` +
    ``emit``; every decoded element is born with the same injected DI.
    Boundary validation (PY-EH-1) routes through ``ElementWireContext``
    so a non-string ``id`` raises a typed ``ValueError`` with the
    offending field named in the message.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[CheckboxElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[CheckboxElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> CheckboxElement:
        """Construct a CheckboxElement from a JSON-decoded mapping.

        Registers a default no-op ``ValueChanged`` handler so
        ``wrap_handlers_for_remote`` has a handler to wrap on the
        Display side. Buttons get handlers from the wire JSON; for
        checkboxes the "forward value changes" behavior is implicit.
        """
        from punt_lux.domain.interaction import ValueChanged  # noqa: PLC0415

        ctx = ElementWireContext.for_kind("checkbox")
        elem = self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            label=ctx.optional_str(raw, "label", default=""),
            value=ctx.optional_bool(raw, "value", default=False),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        elem.add_handler(ValueChanged, _UpdateValueHandler(elem))
        return elem


class JsonCheckboxEncoder:
    """Encode a ``CheckboxElement`` to its JSON-compatible wire dict.

    Stateless. ``tooltip`` is omitted when absent so the wire shape
    matches the prior dataclass codec byte-for-byte.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: CheckboxElement) -> dict[str, object]:
        """Serialize a CheckboxElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "label": elem.label,
                "value": elem.value,
                "tooltip": elem.tooltip,
            }
        )
