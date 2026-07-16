"""JsonRadioDecoder + JsonRadioEncoder — wire codec for ``RadioElement``.

Per the checkbox/checkbox_codec split: the codec body lives here, and
``RadioElement.to_dict`` / ``RadioElement.from_dict`` remain short delegators so
the runtime-checkable ``domain.element.Element`` Protocol stays satisfied. The
decoder injects the tier's ``renderer_factory`` + ``emit`` at construction so the
element is born with its DI wired in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.value_change_handlers import ApplyPatchOnChange
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.radio import RadioElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonRadioDecoder", "JsonRadioEncoder"]


_RADIO_EVENT_TYPES: dict[str, type[ValueChanged]] = {"changed": ValueChanged}


class JsonRadioDecoder:
    """Decode a wire dict to a fully-constructed ``RadioElement``.

    Constructed once per tier with that tier's ``renderer_factory`` + ``emit`` +
    ``HandlerDecoder``. Parallel to ``JsonCheckboxDecoder``: always registers the
    built-in ``ApplyPatchOnChange`` for state sync, then installs any
    wire-declared handlers from the ``handlers`` key.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[RadioElement]
    _handler_decoder: HandlerDecoder[ValueChanged]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[RadioElement],
        handler_decoder: HandlerDecoder[ValueChanged],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> RadioElement:
        """Construct a RadioElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("radio")
        elem = self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            label=ctx.optional_str(raw, "label", default=""),
            items=ctx.optional_string_list(raw, "items"),
            selected=ctx.optional_int_with_default(raw, "selected", default=0),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        elem.add_handler(ValueChanged, ApplyPatchOnChange(elem, field="selected"))
        self._install_handlers(elem, raw)
        return elem

    def _install_handlers(self, elem: RadioElement, raw: Mapping[str, object]) -> None:
        """Install value-changed handlers declared by the wire ``handlers`` list."""
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = f"radio 'handlers' must be a list, got {type(handlers_raw).__name__}"
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                msg = (
                    f"radio 'handlers[{i}]' must be a mapping, "
                    f"got {type(spec).__name__}"
                )
                raise TypeError(msg)
            spec_map = cast("Mapping[str, object]", spec)
            event_type = self._resolve_event_type(spec_map, i)
            handler = self._handler_decoder.decode_spec(spec_map)
            elem.add_handler(event_type, handler)

    @staticmethod
    def _resolve_event_type(
        spec: Mapping[str, object], index: int
    ) -> type[ValueChanged]:
        """Map the wire ``event`` string to its typed event class."""
        event_name = spec.get("event")
        if not isinstance(event_name, str) or not event_name:
            msg = (
                f"radio 'handlers[{index}]' requires an 'event' string, "
                f"got {event_name!r}"
            )
            raise ValueError(msg)
        event_type = _RADIO_EVENT_TYPES.get(event_name)
        if event_type is None:
            known = sorted(_RADIO_EVENT_TYPES)
            msg = (
                f"radio 'handlers[{index}].event' = {event_name!r} is not "
                f"recognised (expected one of {known})"
            )
            raise ValueError(msg)
        return event_type


class JsonRadioEncoder:
    """Encode a ``RadioElement`` to its JSON-compatible wire dict.

    Stateless. ``tooltip`` is omitted when absent via ``strip_none`` so the wire
    for a tooltip-less radio matches the prior dataclass codec byte-for-byte; a
    present tooltip now round-trips (the legacy ``to_dict`` silently dropped it).
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: RadioElement) -> dict[str, object]:
        """Serialize a RadioElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "label": elem.label,
                "items": elem.items,
                "selected": elem.selected,
                "tooltip": elem.tooltip,
            }
        )
