"""Wire-path tests: basics elements flow through Display.apply unchanged.

Each commit in the basics migration adds one class to the matrix below.
Per the migration plan, every kind must satisfy:

1. ``isinstance(elem, Element)`` is True against the domain Protocol.
2. ``element_from_dict({...})`` returns the typed class with no helpers.
3. ``Display.apply(client, AddElement(scene, elem))`` returns ElementAdded
   and the snapshot reflects the element.
4. Wire round-trip: ``element_to_dict(elem)`` produces byte-identical
   output to the pre-migration codec (asserted by make snapshot-parity).

Commit 4 covers TextElement; commits 5-9 add Image, Separator, Progress,
Spinner, Markdown.
"""

from __future__ import annotations

from punt_lux.domain import ElementId, SceneId
from punt_lux.domain.display import Display
from punt_lux.domain.element import Element
from punt_lux.domain.event import ElementAdded
from punt_lux.domain.update import AddElement
from punt_lux.protocol import (
    TextElement,
    element_from_dict,
    element_to_dict,
)


def test_text_element_satisfies_element_protocol() -> None:
    elem = TextElement(id="t1", content="hello")
    assert isinstance(elem, Element)


def test_text_element_to_dict_strips_absent_optionals() -> None:
    elem = TextElement(id="t1", content="hello")
    # absent style and color are dropped to match the pre-migration wire shape.
    assert element_to_dict(elem) == {
        "id": "t1",
        "kind": "text",
        "content": "hello",
    }


def test_text_element_to_dict_emits_style_and_color_when_set() -> None:
    elem = TextElement(id="t1", content="hi", style="heading", color="#FF0000")
    assert element_to_dict(elem) == {
        "id": "t1",
        "kind": "text",
        "content": "hi",
        "style": "heading",
        "color": "#FF0000",
    }


def test_text_element_to_dict_includes_tooltip_when_set() -> None:
    elem = TextElement(id="t1", content="hi", tooltip="hover help")
    payload = element_to_dict(elem)
    assert payload["tooltip"] == "hover help"


def test_text_element_from_dict_round_trips_via_class_method() -> None:
    payload = {
        "kind": "text",
        "id": "t1",
        "content": "hello",
        "style": "caption",
        "color": "#888888",
    }
    elem = element_from_dict(payload)
    assert isinstance(elem, TextElement)
    assert elem.id == "t1"
    assert elem.content == "hello"
    assert elem.style == "caption"
    assert elem.color == "#888888"


def test_text_element_from_dict_accepts_arbitrary_style_string() -> None:
    """PR 1 keeps ``style: str | None`` to preserve wire shape (deferred tighten).

    The renderer treats unknown styles as falling back to default body styling,
    so accepting any string here is byte-compatible with the pre-migration codec.
    """
    payload = {"kind": "text", "id": "t1", "content": "hi", "style": "fancy"}
    elem = element_from_dict(payload)
    assert isinstance(elem, TextElement)
    assert elem.style == "fancy"


def test_text_element_wire_path_through_display_apply() -> None:
    """Wire-decoded TextElement reaches Display.apply and emits ElementAdded."""
    display = Display()
    client = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))

    wire = {"kind": "text", "id": "t1", "content": "hello"}
    elem = element_from_dict(wire)
    assert isinstance(elem, TextElement)

    result = display.apply(client, AddElement(scene_id=SceneId("s1"), element=elem))
    assert isinstance(result, ElementAdded)
    assert result.element_id == ElementId("t1")

    snap = display.snapshot(SceneId("s1"))
    stored = snap.element(ElementId("t1"))
    assert isinstance(stored, TextElement)
    assert stored.content == "hello"


def test_text_element_codec_helpers_are_gone() -> None:
    """PL-PP-1: deleted helpers leave no shim behind."""
    from punt_lux.protocol.elements import basics

    assert not hasattr(basics, "_text_to_dict")
    assert not hasattr(basics, "_text_from_dict")
