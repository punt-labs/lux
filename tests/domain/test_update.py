"""Verify Update sum types: AddElement / RemoveElement / SetProperty."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

import pytest

from punt_lux.domain import ElementId, SceneId
from punt_lux.domain.update import (
    AddElement,
    ElementDecoder,
    RemoveElement,
    SetProperty,
)


@dataclass(frozen=True, slots=True)
class _FakeElement:
    """Minimal Element-conforming class used to round-trip AddElement."""

    id: ElementId
    content: str
    kind: Literal["fake"] = "fake"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": str(self.id), "kind": self.kind, "content": self.content}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=ElementId(str(d["id"])), content=str(d.get("content", "")))


def _decode(d: Mapping[str, object]) -> _FakeElement:
    return _FakeElement.from_dict(d)


def test_add_element_round_trip() -> None:
    update = AddElement(
        scene_id=SceneId("s1"),
        element=_FakeElement(id=ElementId("e1"), content="hi"),
        parent_id=None,
    )
    payload = update.to_dict()
    assert payload["kind"] == "add_element"
    assert payload["scene_id"] == "s1"
    restored = AddElement.from_dict(payload, decode_element=_decode)
    assert restored.scene_id == update.scene_id
    assert restored.parent_id is None


def test_add_element_with_parent_round_trip() -> None:
    update = AddElement(
        scene_id=SceneId("s1"),
        element=_FakeElement(id=ElementId("e1"), content="hi"),
        parent_id=ElementId("group1"),
    )
    payload = update.to_dict()
    assert payload["parent_id"] == "group1"
    restored = AddElement.from_dict(payload, decode_element=_decode)
    assert restored.parent_id == ElementId("group1")


def test_add_element_rejects_bad_parent_id() -> None:
    payload = {
        "kind": "add_element",
        "scene_id": "s1",
        "element": {"id": "e1", "kind": "fake", "content": "x"},
        "parent_id": 7,
    }
    with pytest.raises(ValueError, match="parent_id"):
        AddElement.from_dict(payload, decode_element=_decode)


def test_remove_element_round_trip() -> None:
    update = RemoveElement(scene_id=SceneId("s1"), element_id=ElementId("e1"))
    payload = update.to_dict()
    restored = RemoveElement.from_dict(payload)
    assert restored == update


def test_set_property_round_trip() -> None:
    update = SetProperty(
        scene_id=SceneId("s1"),
        element_id=ElementId("e1"),
        field="content",
        value="hello",
    )
    payload = update.to_dict()
    restored = SetProperty.from_dict(payload)
    assert restored == update


def test_set_property_value_preserves_none() -> None:
    """A genuine None value passes through (not the same as missing key)."""
    update = SetProperty(
        scene_id=SceneId("s1"),
        element_id=ElementId("e1"),
        field="tooltip",
        value=None,
    )
    payload = update.to_dict()
    restored = SetProperty.from_dict(payload)
    assert restored.value is None


def test_set_property_rejects_missing_value_key() -> None:
    """Copilot CP-6: a payload without the ``value`` key is malformed.

    ``d.get("value")`` previously coalesced this with explicit-null,
    silently accepting both.  The fix raises on missing key while still
    accepting explicit ``None`` (verified by the test above).
    """
    payload = {
        "kind": "set_property",
        "scene_id": "s1",
        "element_id": "e1",
        "field": "tooltip",
    }
    with pytest.raises(ValueError, match=r"SetProperty missing required field 'value'"):
        SetProperty.from_dict(payload)


def test_remove_element_rejects_missing_scene_id() -> None:
    with pytest.raises(ValueError, match="scene_id"):
        RemoveElement.from_dict({"kind": "remove_element", "element_id": "e1"})


def test_element_decoder_alias_is_callable() -> None:
    """ElementDecoder is the callable wire-decode contract."""
    decoder: ElementDecoder = _decode
    elem = decoder({"id": "e1", "kind": "fake", "content": "x"})
    assert elem.id == ElementId("e1")
