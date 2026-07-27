"""JsonModalDecoder + JsonModalEncoder — wire codec for the ABC ``ModalElement``.

Mirrors two exemplars: the collapsing-header codec (child recursion through the
shared container dispatcher, plus a built-in handler registered before any wire
handlers so ``fire`` has a bucket and the Hub has authoritative behavior when
``ModalClosed`` crosses back) and the dialog codec (the ``install_children`` seam
onto a composite whose model is bound at construction).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.domain.container_interaction import ModalClosed
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.protocol.elements.modal import ModalElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder

__all__ = ["JsonModalDecoder", "JsonModalEncoder"]

# Injected child decoder: the tier's ``element_from_dict`` bound method.
type DecodeElement = Callable[[dict[str, Any]], object]


class _DismissOnClose:
    """Serializable handler that dismisses a modal when the user closes it.

    On the Hub side it calls ``model.close`` — which flips visibility and fires
    the ``mark_removed`` cascade so the removal drops the modal from the store
    and both tiers converge. On the Display side ``wrap_handlers_for_remote``
    folds it into a forward-only ``RemoteDispatchGroup``, so the Display never
    runs it; the close it observes is sent to the Hub instead.
    """

    _elem: ModalElement

    def __new__(cls, elem: ModalElement) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (object.__new__, (type(self),), {"_elem": self._elem})

    def __setstate__(self, state: dict[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @trace
    def __call__(self, _event: ModalClosed) -> None:
        self._elem.model.close()


class JsonModalDecoder:
    """Decode a wire dict to a fully-constructed ABC ``ModalElement``.

    Constructed once per tier. Builds the modal (which binds its model), recurses
    the body children through the injected tier decoder, then always registers the
    built-in ``_DismissOnClose`` handler before installing any wire handlers.
    """

    _decode_element: DecodeElement
    _cls: type[ModalElement]
    _handler_decoder: HandlerDecoder[ModalClosed]

    def __new__(
        cls,
        *,
        decode_element: DecodeElement,
        element_cls: type[ModalElement],
        handler_decoder: HandlerDecoder[ModalClosed],
    ) -> Self:
        self = super().__new__(cls)
        self._decode_element = decode_element
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> ModalElement:
        """Construct the modal, recursing its body children through the tier."""
        ctx = ElementWireContext.for_kind("modal")
        modal = self._cls(
            id=ctx.require_id(raw),
            title=ctx.optional_str(raw, "title", default=""),
            open=ctx.optional_bool(raw, "open", default=True),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        children = ctx.decode_children(
            modal.id, self._require_list(raw.get("children")), self._decode
        )
        modal.install_children(children)
        modal.add_handler(ModalClosed, _DismissOnClose(modal))
        self._install_handlers(modal, raw)
        return modal

    def _decode(self, raw_child: object) -> Element:
        """Decode one wire child through the injected tier decoder."""
        child = cast("dict[str, Any]", raw_child)
        return cast("Element", self._decode_element(child))

    def _install_handlers(self, elem: ModalElement, raw: Mapping[str, object]) -> None:
        """Install modal-closed handlers declared by the wire ``handlers`` list."""
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = f"modal 'handlers' must be a list, got {type(handlers_raw).__name__}"
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                msg = (
                    f"modal 'handlers[{i}]' must be a mapping, "
                    f"got {type(spec).__name__}"
                )
                raise TypeError(msg)
            spec_map = cast("Mapping[str, object]", spec)
            self._require_close_event(spec_map, i)
            handler = self._handler_decoder.decode_spec(spec_map)
            elem.add_handler(ModalClosed, handler)

    @staticmethod
    def _require_close_event(spec: Mapping[str, object], index: int) -> None:
        """Reject a wire handler whose ``event`` is not the modal's ``closed``.

        ``closed`` is the sole event a modal emits; a mismatch fails loud at
        decode rather than silently binding a handler that can never fire.
        """
        event_name = spec.get("event")
        if event_name != "closed":
            msg = (
                f"modal 'handlers[{index}].event' = {event_name!r} is not "
                "recognised (expected 'closed')"
            )
            raise ValueError(msg)

    @staticmethod
    def _require_list(raw: object) -> list[object]:
        """Return ``raw`` as a list; ``[]`` absent, raising a present non-list."""
        if raw is None:
            return []
        if not isinstance(raw, list):
            msg = f"modal children must be a list, got {type(raw).__name__}"
            raise TypeError(msg)
        return cast("list[object]", raw)


class JsonModalEncoder:
    """Encode an ABC ``ModalElement`` to its JSON-compatible wire dict.

    Stateless. Emits ``open`` (the current model visibility) and ``children``
    always, ``tooltip`` only when set.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: ModalElement) -> dict[str, object]:
        """Serialize a ModalElement to a JSON-compatible dict."""
        recurse = dispatch.to_dict
        payload: dict[str, object] = {
            "kind": "modal",
            "id": elem.id,
            "title": elem.title,
            "open": elem.open,
            "children": [recurse(child) for child in elem.children],
        }
        if elem.tooltip is not None:
            payload["tooltip"] = elem.tooltip
        return payload
