"""Button publish-on-click attribute: roundtrip, validation, and Hub-side fire.

The typed ``publish`` attribute rides beside the button's existing on-click
handler path. These tests cover the four surfaces the migration gate cares
about: the JSON codec roundtrip (Level 1), the native-pickle scene wire (Level
2), self-validation (DES-039), and the Hub-side fire that fans the declared
topic out through a real ``PublishSink`` — composed with an ordinary click
handler, never replacing it.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_publish import ButtonPublish
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderers.raising import RaisingRendererFactory


class _RecordingSink:
    """A ``PublishSink`` that records every ``(topic, payload)`` it is handed."""

    __slots__ = ("calls",)

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        self.calls.append((topic, dict(payload)))


def _click(element_id: str) -> ButtonClicked:
    return ButtonClicked(
        scene_id=SceneId("s"),
        element_id=ElementId(element_id),
        owner_id=ClientId("owner"),
    )


# -- Level 1: JSON codec roundtrip ------------------------------------------


def test_button_publish_json_roundtrip_preserves_topic_and_payload() -> None:
    button = ButtonElement(
        id="play", label="Play", publish=ButtonPublish("music.play", {"album_id": "a1"})
    )
    restored = ButtonElement.from_dict(button.to_dict())
    assert restored.publish == ButtonPublish("music.play", {"album_id": "a1"})


def test_button_without_publish_omits_the_wire_field() -> None:
    wire = ButtonElement(id="b", label="B").to_dict()
    assert "publish" not in wire


def test_button_publish_empty_payload_roundtrips_to_empty_mapping() -> None:
    button = ButtonElement(id="stop", label="Stop", publish=ButtonPublish("music.stop"))
    wire = button.to_dict()
    assert wire["publish"] == {"topic": "music.stop"}
    restored = ButtonElement.from_dict(wire)
    assert restored.publish == ButtonPublish("music.stop", {})


# -- Level 2: native-pickle scene wire --------------------------------------


def test_button_publish_survives_the_scene_pickle_wire() -> None:
    button = ButtonElement(id="play", publish=ButtonPublish("music.play", {"x": 1}))
    wire = message_to_dict(SceneMessage(id="s1", elements=[button], frame_id="s1"))
    restored = message_from_dict(wire)
    assert isinstance(restored, SceneMessage)
    element = restored.elements[0]
    assert isinstance(element, ButtonElement)
    assert element.publish == ButtonPublish("music.play", {"x": 1})


# -- Self-validation (DES-039) ----------------------------------------------


def test_valid_publish_declaration_validates_clean() -> None:
    button = ButtonElement(id="b", publish=ButtonPublish("music.play", {"a": 1}))
    assert button.validate() == ()


def test_empty_topic_is_a_named_validation_error() -> None:
    button = ButtonElement(id="b", publish=ButtonPublish("", {"a": 1}))
    errors = button.validate()
    assert len(errors) == 1
    assert errors[0].element_id == "b"
    assert errors[0].element_kind == "button"
    assert "topic" in errors[0].message


def test_absent_publish_validates_clean() -> None:
    assert ButtonElement(id="b").validate() == ()


# -- Structural rejection at decode -----------------------------------------


def test_non_mapping_publish_is_rejected_at_decode() -> None:
    with pytest.raises(TypeError, match="publish' must be a mapping"):
        ButtonElement.from_dict({"kind": "button", "id": "b", "publish": ["t"]})


def test_non_string_topic_is_rejected_at_decode() -> None:
    with pytest.raises(TypeError, match=r"publish\.topic' must be a string"):
        ButtonElement.from_dict({"kind": "button", "id": "b", "publish": {"topic": 7}})


def test_non_mapping_payload_is_rejected_at_decode() -> None:
    with pytest.raises(TypeError, match=r"publish\.payload' must be a mapping"):
        ButtonElement.from_dict(
            {"kind": "button", "id": "b", "publish": {"topic": "t", "payload": [1]}}
        )


# -- Hub-side fire publishes through the sink --------------------------------


def _hub_decode(sink: _RecordingSink, raw: dict[str, object]) -> ButtonElement:
    factory = JsonElementFactory(
        renderer_factory=RaisingRendererFactory(),
        emit=lambda _msg: None,
        publish_sink=sink,
    )
    button = factory.decode(raw)
    assert isinstance(button, ButtonElement)
    return button


def test_fire_publishes_the_declared_topic_and_payload() -> None:
    sink = _RecordingSink()
    button = _hub_decode(
        sink,
        {
            "kind": "button",
            "id": "play",
            "publish": {"topic": "music.play", "payload": {"album_id": "a1"}},
        },
    )
    button.fire(_click("play"))
    assert sink.calls == [("music.play", {"album_id": "a1"})]


def test_publish_composes_with_the_existing_click_handler() -> None:
    sink = _RecordingSink()
    button = _hub_decode(
        sink,
        {
            "kind": "button",
            "id": "play",
            "publish": {"topic": "music.play", "payload": {"album_id": "a1"}},
        },
    )
    ran: list[str] = []
    button.add_handler(ButtonClicked, lambda _e: ran.append("extra"))
    button.fire(_click("play"))
    assert sink.calls == [("music.play", {"album_id": "a1"})]
    assert ran == ["extra"]


def test_list_publish_sugar_still_fans_empty_payloads() -> None:
    sink = _RecordingSink()
    button = _hub_decode(
        sink, {"kind": "button", "id": "b", "publish": ["topic.a", "topic.b"]}
    )
    assert button.publish is None  # list form is decorator sugar, not the attribute
    button.fire(_click("b"))
    assert sink.calls == [("topic.a", {}), ("topic.b", {})]
