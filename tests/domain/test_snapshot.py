"""Verify SceneSnapshot is read-only and raises KeyError on absent elements."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

import pytest

from punt_lux.domain import ElementId, SceneId
from punt_lux.domain.snapshot import SceneSnapshot


@dataclass(frozen=True, slots=True)
class _Elem:
    id: ElementId
    label: str
    kind: Literal["fake"] = "fake"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": str(self.id), "kind": self.kind, "label": self.label}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=ElementId(str(d["id"])), label=str(d.get("label", "")))


def test_snapshot_returns_element_by_id() -> None:
    elem = _Elem(id=ElementId("e1"), label="hi")
    snap = SceneSnapshot(SceneId("s1"), {ElementId("e1"): elem})
    assert snap.element(ElementId("e1")) is elem


def test_snapshot_raises_keyerror_on_missing_element() -> None:
    snap = SceneSnapshot(SceneId("s1"), {})
    with pytest.raises(KeyError, match="no such element"):
        snap.element(ElementId("ghost"))


def test_snapshot_has_returns_membership() -> None:
    elem = _Elem(id=ElementId("e1"), label="hi")
    snap = SceneSnapshot(SceneId("s1"), {ElementId("e1"): elem})
    assert snap.has(ElementId("e1"))
    assert not snap.has(ElementId("ghost"))


def test_snapshot_is_decoupled_from_source_mapping() -> None:
    source: dict[ElementId, _Elem] = {
        ElementId("e1"): _Elem(id=ElementId("e1"), label="hi"),
    }
    snap = SceneSnapshot(SceneId("s1"), source)
    source.clear()  # Mutate the source after snapshotting.
    assert snap.has(ElementId("e1"))


def test_snapshot_exposes_scene_id_and_element_ids() -> None:
    elem = _Elem(id=ElementId("e1"), label="hi")
    snap = SceneSnapshot(SceneId("s1"), {ElementId("e1"): elem})
    assert snap.scene_id == SceneId("s1")
    assert snap.element_ids == frozenset({ElementId("e1")})
