"""JsonComboDecoder + JsonComboEncoder — wire codec for ``ComboElement``.

Per the checkbox/checkbox_codec split: the codec body lives here, and
``ComboElement.to_dict`` / ``ComboElement.from_dict`` remain short delegators so
the runtime-checkable ``domain.element.Element`` Protocol stays satisfied. The
decoder injects the tier's ``renderer_factory`` + ``emit`` at construction so the
element is born with its DI wired in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.combo import ComboElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonComboDecoder", "JsonComboEncoder"]


class _UpdateSelectedHandler:
    """Serializable handler that updates a combo's selection on pick.

    On the Hub side this runs when ``ValueChanged`` fires — updating the
    authoritative ``selected`` index via ``apply_patch``. On the Display side,
    ``wrap_handlers_for_remote`` wraps it in a ``RemoteDispatchGroup`` that sends
    the interaction to the Hub.
    """

    _elem: ComboElement

    def __new__(cls, elem: ComboElement) -> Self:
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
        self._elem.apply_patch({"selected": event.value})


_COMBO_EVENT_TYPES: dict[str, type[ValueChanged]] = {"changed": ValueChanged}


class JsonComboDecoder:
    """Decode a wire dict to a fully-constructed ``ComboElement``.

    Constructed once per tier with that tier's ``renderer_factory`` + ``emit`` +
    ``HandlerDecoder``. Parallel to ``JsonCheckboxDecoder``: always registers the
    built-in ``_UpdateSelectedHandler`` for state sync, then installs any
    wire-declared handlers from the ``handlers`` key.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[ComboElement]
    _handler_decoder: HandlerDecoder[ValueChanged]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[ComboElement],
        handler_decoder: HandlerDecoder[ValueChanged],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> ComboElement:
        """Construct a ComboElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("combo")
        elem = self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            label=ctx.optional_str(raw, "label", default=""),
            items=ctx.optional_string_list(raw, "items"),
            selected=ctx.optional_int_with_default(raw, "selected", default=0),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        elem.add_handler(ValueChanged, _UpdateSelectedHandler(elem))
        self._install_handlers(elem, raw)
        return elem

    def _install_handlers(self, elem: ComboElement, raw: Mapping[str, object]) -> None:
        """Install value-changed handlers declared by the wire ``handlers`` list."""
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = f"combo 'handlers' must be a list, got {type(handlers_raw).__name__}"
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                msg = (
                    f"combo 'handlers[{i}]' must be a mapping, "
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
                f"combo 'handlers[{index}]' requires an 'event' string, "
                f"got {event_name!r}"
            )
            raise ValueError(msg)
        event_type = _COMBO_EVENT_TYPES.get(event_name)
        if event_type is None:
            known = sorted(_COMBO_EVENT_TYPES)
            msg = (
                f"combo 'handlers[{index}].event' = {event_name!r} is not "
                f"recognised (expected one of {known})"
            )
            raise ValueError(msg)
        return event_type


class JsonComboEncoder:
    """Encode a ``ComboElement`` to its JSON-compatible wire dict.

    Stateless. ``tooltip`` is omitted when absent via ``strip_none`` so the wire
    for a tooltip-less combo matches the prior dataclass codec byte-for-byte; a
    present tooltip now round-trips (the legacy ``to_dict`` silently dropped it).
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: ComboElement) -> dict[str, object]:
        """Serialize a ComboElement to a JSON-compatible dict."""
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
