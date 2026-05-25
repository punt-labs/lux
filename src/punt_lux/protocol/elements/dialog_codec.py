"""JsonDialogDecoder + JsonDialogEncoder — wire codec for ``DialogElement``.

The dialog decoder is the canonical example of the bound-callback
pattern for composite Elements: it constructs the ``DialogElement``
(which constructs its model with ``on_dismiss=self.mark_removed``),
then decodes each child Button with a per-dialog ``HandlerDecoder``
configured to resolve ``call_model`` verbs against the dialog's model
through ``BoundVerb.resolve_against``.

Failures are loud and at decode time: an unknown verb, a malformed
handler spec, a missing ``id``, or — critically — a missing
``publish_sink`` at decoder construction all raise before the dialog
is added to the scene. There is no silent sink: the decoder refuses to
construct without a real publish channel, so a wire spec carrying a
``publish`` decorator can never silently land in a void.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import ButtonHandlers, DecoratorRegistry
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.handlers.verb_vocabulary import BoundVerb
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonDecoder
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.dialog import DialogElement, DialogModel
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonDialogDecoder", "JsonDialogEncoder"]


class JsonDialogDecoder:
    """Decode a wire dict to a fully-constructed ``DialogElement``.

    Constructed once per tier with that tier's ``renderer_factory``,
    ``emit``, and a real ``PublishSink``. The sink is REQUIRED — a
    decoder without a sink cannot honour a child Button's ``publish``
    decorator, and the directive bans silent fallbacks. Construction
    raises ``TypeError`` if any required arg is missing.

    Each ``decode`` call builds the dialog element, then walks the
    ``children`` list and decodes each as a Button against the
    dialog's model.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[DialogElement]
    _sink: PublishSink

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[DialogElement],
        publish_sink: PublishSink,
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        self._sink = publish_sink
        return self

    def decode(self, raw: Mapping[str, object]) -> DialogElement:
        """Construct a DialogElement and wire its children to the model."""
        ctx = ElementWireContext.for_kind("dialog")
        dialog = self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            title=ctx.optional_str(raw, "title", default=""),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        children = self._decode_children(raw, dialog.model)
        dialog.install_children(children)
        return dialog

    def _decode_children(
        self, raw: Mapping[str, object], model: DialogModel
    ) -> tuple[ButtonElement, ...]:
        """Walk the wire ``children`` list and decode each as a Button."""
        children_raw = raw.get("children")
        if children_raw is None:
            return ()
        if not isinstance(children_raw, list):
            msg = f"dialog 'children' must be a list, got {type(children_raw).__name__}"
            raise TypeError(msg)
        button_decoder = self._build_button_decoder(model)
        decoded: list[ButtonElement] = []
        for i, child_raw in enumerate(cast("list[object]", children_raw)):
            if not isinstance(child_raw, dict):
                msg = (
                    f"dialog 'children[{i}]' must be a mapping, "
                    f"got {type(child_raw).__name__}"
                )
                raise TypeError(msg)
            child_map = cast("Mapping[str, object]", child_raw)
            kind = child_map.get("kind")
            if kind != "button":
                msg = f"dialog 'children[{i}]' must have kind='button', got {kind!r}"
                raise ValueError(msg)
            child_map = self._canonicalize_button_sugar(child_map)
            decoded.append(button_decoder.decode(child_map))
        return tuple(decoded)

    @staticmethod
    def _canonicalize_button_sugar(
        raw: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Promote top-level ``click`` and ``publish`` sugar on a child button."""
        from punt_lux.protocol.element_factory import JsonElementFactory

        return JsonElementFactory.canonicalize_button_sugar(raw)

    def _build_button_decoder(self, model: DialogModel) -> JsonButtonDecoder:
        """Build a per-dialog Button decoder bound to ``model``'s verbs."""
        factories: FactoryRegistry[ButtonClicked] = FactoryRegistry()

        def _build_noop(_params: Mapping[str, object]) -> Handler[ButtonClicked]:
            return ButtonHandlers.noop()

        def _build_call_model(
            params: Mapping[str, object],
        ) -> Handler[ButtonClicked]:
            verb_raw = params.get("verb")
            if not isinstance(verb_raw, str) or not verb_raw:
                msg = (
                    f"dialog child handler 'call_model' requires 'verb' string, "
                    f"got {verb_raw!r}"
                )
                raise ValueError(msg)
            bound = BoundVerb.resolve_against(model, verb_raw)
            return ButtonHandlers.call_model(bound)

        factories.register("noop", _build_noop)
        factories.register("call_model", _build_call_model)
        decorators = DecoratorRegistry(sink=self._sink)
        handler_decoder: HandlerDecoder[ButtonClicked] = HandlerDecoder(
            factories=factories, decorators=decorators
        )
        return JsonButtonDecoder(
            renderer_factory=self._rf,
            emit=self._emit,
            element_cls=ButtonElement,
            handler_decoder=handler_decoder,
        )


class JsonDialogEncoder:
    """Encode a ``DialogElement`` to its JSON-compatible wire dict.

    Stateless. The encoder writes only the structural surface — id,
    title, child kinds — not the handler specs that produced the
    children's behaviour. Re-encoding a decoded dialog yields a wire
    shape an agent could re-decode against the same model.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: DialogElement) -> dict[str, object]:
        """Serialize a DialogElement to a JSON-compatible dict."""
        payload: dict[str, object | None] = {
            "kind": elem.kind,
            "id": elem.id,
            "title": elem.title or None,
            "tooltip": elem.tooltip,
        }
        children = elem.children
        if children:
            payload["children"] = [self._encode_child(c) for c in children]
        return strip_none(payload)

    @staticmethod
    def _encode_child(child: object) -> dict[str, object]:
        """Encode a child element through its own ``to_dict`` if available."""
        if isinstance(child, ButtonElement):
            return child.to_dict()
        msg = f"DialogElement child has no encoder: {type(child).__name__}"
        raise TypeError(msg)
