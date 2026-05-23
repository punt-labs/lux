"""Per-kind Json Decoders + Encoders + registries.

Each Element kind has its own Json{Kind}Decoder and Json{Kind}Encoder.
The DecoderFactory dispatches by `"kind"` field; the EncoderFactory
dispatches by Element type. Encoder takes the Element state directly
(NOT an intermediate render product — that would be the rejected
RemoteRenderer pattern).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lux_spike.elements import ButtonElement, LabelElement, PanelElement
from lux_spike.updates import AddElement, ButtonClicked, InteractionMessage, RemoveElement, SetProperty

if TYPE_CHECKING:
    from lux_spike.element import Element
    from lux_spike.protocols import Emit, RendererFactory


# ───────────────────── Element decoders (wire → Element) ──────────────────────


class JsonLabelDecoder:
    _rf: RendererFactory
    _emit: Emit

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit) -> "JsonLabelDecoder":
        self = object.__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        return self

    def decode(self, raw: dict[str, object]) -> LabelElement:
        return LabelElement(
            renderer_factory=self._rf,
            emit=self._emit,
            id=str(raw["id"]),
            content=str(raw["content"]),
        )


class JsonButtonDecoder:
    _rf: RendererFactory
    _emit: Emit

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit) -> "JsonButtonDecoder":
        self = object.__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        return self

    def decode(self, raw: dict[str, object]) -> ButtonElement:
        return ButtonElement(
            renderer_factory=self._rf,
            emit=self._emit,
            id=str(raw["id"]),
            label=str(raw["label"]),
        )


class JsonPanelDecoder:
    _rf: RendererFactory
    _emit: Emit
    _factory: "JsonElementFactory"

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        factory: "JsonElementFactory",
    ) -> "JsonPanelDecoder":
        self = object.__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._factory = factory
        return self

    def decode(self, raw: dict[str, object]) -> PanelElement:
        children_raw = raw.get("children", [])
        assert isinstance(children_raw, list)
        children = tuple(self._factory.decode(c) for c in children_raw)
        return PanelElement(
            renderer_factory=self._rf,
            emit=self._emit,
            id=str(raw["id"]),
            children=children,
        )


# ───────────────────── DecoderFactory + registry ──────────────────────────────


class JsonElementFactory:
    """Top-level element decoder: dispatches by `"kind"` to per-kind decoder.
    One instance per tier (constructed at startup with the tier's
    RendererFactory + Emit)."""

    _rf: RendererFactory
    _emit: Emit

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit) -> "JsonElementFactory":
        self = object.__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        return self

    def decode(self, raw: dict[str, object]) -> "Element":
        kind = raw.get("kind")
        match kind:
            case "label":
                return JsonLabelDecoder(renderer_factory=self._rf, emit=self._emit).decode(raw)
            case "button":
                return JsonButtonDecoder(renderer_factory=self._rf, emit=self._emit).decode(raw)
            case "panel":
                return JsonPanelDecoder(renderer_factory=self._rf, emit=self._emit, factory=self).decode(raw)
            case _:
                raise ValueError(f"unknown element kind: {kind!r}")


# ───────────────────── Element encoders (Element → wire) ──────────────────────


class JsonLabelEncoder:
    def encode(self, elem: LabelElement) -> dict[str, object]:
        return {"kind": "label", "id": elem.id, "content": elem.content}


class JsonButtonEncoder:
    def encode(self, elem: ButtonElement) -> dict[str, object]:
        return {"kind": "button", "id": elem.id, "label": elem.label}


class JsonPanelEncoder:
    _factory: "JsonEncoderFactory"

    def __new__(cls, *, factory: "JsonEncoderFactory") -> "JsonPanelEncoder":
        self = object.__new__(cls)
        self._factory = factory
        return self

    def encode(self, elem: PanelElement) -> dict[str, object]:
        return {
            "kind": "panel",
            "id": elem.id,
            "children": [self._factory.encode(c) for c in elem._children()],
        }


class JsonEncoderFactory:
    """Top-level element encoder: dispatches by Element type to per-kind."""

    def __new__(cls) -> "JsonEncoderFactory":
        return object.__new__(cls)

    def encode(self, elem: "Element") -> dict[str, object]:
        match elem:
            case LabelElement():
                return JsonLabelEncoder().encode(elem)
            case ButtonElement():
                return JsonButtonEncoder().encode(elem)
            case PanelElement():
                return JsonPanelEncoder(factory=self).encode(elem)
            case _:
                raise ValueError(f"unknown element type: {type(elem).__name__}")


# ───────────────────── Update / Event / Interaction codec ─────────────────────


class UpdateCodec:
    """Encode Updates to wire dicts and decode them back. Updates flow
    Hub → Display; they carry Element state changes."""

    _enc: JsonEncoderFactory
    _dec: JsonElementFactory

    def __new__(cls, *, encoder: JsonEncoderFactory, decoder: JsonElementFactory) -> "UpdateCodec":
        self = object.__new__(cls)
        self._enc = encoder
        self._dec = decoder
        return self

    def encode(self, update: AddElement | SetProperty | RemoveElement) -> dict[str, object]:
        match update:
            case AddElement(scene_id=sid, parent_id=pid, elem=elem, dismiss_on_click=dismiss):
                return {
                    "kind": "add_element",
                    "scene_id": sid,
                    "parent_id": pid,
                    "elem": self._enc.encode(elem),
                    "dismiss_on_click": dismiss,
                }
            case SetProperty(elem_id=eid, field=field, value=value):
                return {
                    "kind": "set_property",
                    "elem_id": eid,
                    "field": field,
                    "value": value,
                }
            case RemoveElement(elem_id=eid):
                return {
                    "kind": "remove_element",
                    "elem_id": eid,
                }

    def decode(self, raw: dict[str, object]) -> AddElement | SetProperty | RemoveElement:
        kind = raw.get("kind")
        match kind:
            case "add_element":
                return AddElement(
                    scene_id=str(raw["scene_id"]),
                    parent_id=raw["parent_id"] if raw["parent_id"] is None else str(raw["parent_id"]),
                    elem=self._dec.decode(raw["elem"]),  # type: ignore[arg-type]
                    dismiss_on_click=bool(raw.get("dismiss_on_click", False)),
                )
            case "set_property":
                return SetProperty(
                    elem_id=str(raw["elem_id"]),
                    field=str(raw["field"]),
                    value=raw["value"],
                )
            case "remove_element":
                return RemoveElement(elem_id=str(raw["elem_id"]))
            case _:
                raise ValueError(f"unknown update kind: {kind!r}")


def encode_interaction(msg: InteractionMessage) -> dict[str, object]:
    return {"kind": "interaction", "elem_id": msg.elem_id, "action": msg.action}


def decode_interaction(raw: dict[str, object]) -> InteractionMessage:
    return InteractionMessage(elem_id=str(raw["elem_id"]), action=str(raw["action"]))


def encode_button_clicked(ev: ButtonClicked) -> dict[str, object]:
    return {"elem_id": ev.elem_id}
