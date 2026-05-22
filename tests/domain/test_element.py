"""Verify Element Protocol is runtime-checkable and detects conformance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from punt_lux.domain import Element, ElementId


@dataclass(frozen=True, slots=True)
class _ConformantElement:
    """Synthetic element used to verify the Protocol's structural check."""

    id: ElementId
    kind: Literal["synthetic"] = "synthetic"

    def to_dict(self) -> dict[str, object]:
        return {"id": str(self.id), "kind": self.kind}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=ElementId(str(d["id"])))


@dataclass(frozen=True, slots=True)
class _NonConformantElement:
    """Missing to_dict / from_dict — must fail isinstance(Element)."""

    id: str
    kind: Literal["broken"] = "broken"


def test_conformant_class_satisfies_element_protocol() -> None:
    elem = _ConformantElement(id=ElementId("e1"))
    assert isinstance(elem, Element)


def test_non_conformant_class_fails_element_protocol() -> None:
    broken = _NonConformantElement(id="e1")
    assert not isinstance(broken, Element)


def test_protocol_round_trip() -> None:
    elem = _ConformantElement(id=ElementId("e1"))
    restored = _ConformantElement.from_dict(elem.to_dict())
    assert restored == elem
