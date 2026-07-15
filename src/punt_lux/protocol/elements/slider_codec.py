"""JsonSliderDecoder + JsonSliderEncoder — wire codec for SliderElement.

The codec body lives in this sibling module rather than on ``SliderElement``;
``to_dict`` / ``from_dict`` stay as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at construction
so the element is born with its DI wired in, and installs the built-in
``_UpdateValueHandler`` that mirrors the authoritative value on every
``ValueChanged`` before decoding any wire-declared handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.slider import SliderElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonSliderDecoder", "JsonSliderEncoder"]


@final
class _UpdateValueHandler:
    """Serializable handler that mirrors a slider's value on a commit.

    On the Hub side, this handler runs when ``ValueChanged`` fires — updating
    the authoritative value via ``apply_patch``. On the Display side,
    ``wrap_handlers_for_remote`` wraps it in a ``RemoteDispatchGroup`` that
    sends the interaction to the Hub instead of running it locally.
    """

    _elem: SliderElement

    def __new__(cls, elem: SliderElement) -> Self:
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


_SLIDER_EVENT_TYPES: dict[str, type[ValueChanged]] = {"changed": ValueChanged}


@final
class JsonSliderDecoder:
    """Decode a wire dict to a fully-constructed ``SliderElement``.

    Constructed once per tier with that tier's ``renderer_factory`` +
    ``emit`` + ``HandlerDecoder``; every decoded element is born with the
    same injected DI. Boundary validation (PY-EH-1) routes through
    ``ElementWireContext`` so a non-numeric ``value`` or missing ``id`` raises
    a typed ``ValueError`` naming the offending field. Always registers the
    built-in ``_UpdateValueHandler`` for state sync, then installs any
    wire-declared handlers from the ``handlers`` key.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[SliderElement]
    _handler_decoder: HandlerDecoder[ValueChanged]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[SliderElement],
        handler_decoder: HandlerDecoder[ValueChanged],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> SliderElement:
        """Construct a SliderElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("slider")
        elem = self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            label=ctx.optional_str(raw, "label", default=""),
            value=ctx.optional_number(raw, "value", default=0.0),
            min=ctx.optional_number(raw, "min", default=0.0),
            max=ctx.optional_number(raw, "max", default=100.0),
            format=ctx.optional_nullable_str(raw, "format"),
            integer=ctx.optional_bool(raw, "integer", default=False),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        elem.add_handler(ValueChanged, _UpdateValueHandler(elem))
        self._install_handlers(elem, raw)
        return elem

    def _install_handlers(self, elem: SliderElement, raw: Mapping[str, object]) -> None:
        """Install value-changed handlers declared by the wire ``handlers`` list."""
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = f"slider 'handlers' must be a list, got {type(handlers_raw).__name__}"
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                msg = (
                    f"slider 'handlers[{i}]' must be a mapping, "
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
                f"slider 'handlers[{index}]' requires an 'event' string, "
                f"got {event_name!r}"
            )
            raise ValueError(msg)
        event_type = _SLIDER_EVENT_TYPES.get(event_name)
        if event_type is None:
            known = sorted(_SLIDER_EVENT_TYPES)
            msg = (
                f"slider 'handlers[{index}].event' = {event_name!r} is not "
                f"recognised (expected one of {known})"
            )
            raise ValueError(msg)
        return event_type


@final
class JsonSliderEncoder:
    """Encode a ``SliderElement`` to its JSON-compatible wire dict.

    Stateless. ``integer`` is emitted only when ``True`` and ``tooltip`` only
    when present, so the wire shape matches the prior dataclass codec
    byte-for-byte in the tooltip-absent case; a present ``tooltip`` is now
    carried (the legacy dataclass codec dropped it — this activates it for
    parity with input_text / checkbox).
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: SliderElement) -> dict[str, object]:
        """Serialize a SliderElement to a JSON-compatible dict."""
        d: dict[str, object] = {
            "kind": elem.kind,
            "id": elem.id,
            "label": elem.label,
            "value": elem.value,
            "min": elem.min,
            "max": elem.max,
            "format": elem.format,
        }
        if elem.integer:
            d["integer"] = True
        if elem.tooltip is not None:
            d["tooltip"] = elem.tooltip
        return d
