"""Unit tests for the hierarchy-walking validation collector."""

from __future__ import annotations

from typing import Self

from punt_lux.domain.validation import ValidationError
from punt_lux.domain.validation_walk import (
    ElementTreeValidator,
    HasChildElements,
    SelfValidating,
)


class _Leaf:
    """A self-validating leaf with a fixed set of errors."""

    __slots__ = ("_errors", "_id")

    _id: str
    _errors: tuple[ValidationError, ...]

    def __new__(cls, element_id: str, errors: tuple[ValidationError, ...]) -> Self:
        self = super().__new__(cls)
        self._id = element_id
        self._errors = errors
        return self

    def validate(self) -> tuple[ValidationError, ...]:
        return self._errors


class _Container:
    """A composite exposing children for the walk (no errors of its own)."""

    __slots__ = ("_children",)

    _children: tuple[object, ...]

    def __new__(cls, children: tuple[object, ...]) -> Self:
        self = super().__new__(cls)
        self._children = children
        return self

    def child_elements(self) -> tuple[object, ...]:
        return self._children


class _Inert:
    """An element that implements neither protocol — the leaf default."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)


def _error(element_id: str) -> ValidationError:
    return ValidationError(element_id=element_id, element_kind="leaf", message="bad")


class TestProtocolMembership:
    def test_leaf_is_self_validating(self) -> None:
        assert isinstance(_Leaf("a", ()), SelfValidating)

    def test_leaf_is_not_a_container(self) -> None:
        assert not isinstance(_Leaf("a", ()), HasChildElements)

    def test_container_has_children(self) -> None:
        assert isinstance(_Container(()), HasChildElements)

    def test_inert_element_satisfies_neither(self) -> None:
        inert = _Inert()
        assert not isinstance(inert, SelfValidating)
        assert not isinstance(inert, HasChildElements)


class TestElementTreeValidator:
    def test_valid_flat_tree_reports_ok(self) -> None:
        report = ElementTreeValidator().validate_tree([_Leaf("a", ()), _Leaf("b", ())])
        assert report.ok

    def test_leaf_errors_collect(self) -> None:
        report = ElementTreeValidator().validate_tree([_Leaf("a", (_error("a"),))])
        assert not report.ok
        assert len(report) == 1

    def test_errors_accumulate_across_siblings_not_fail_fast(self) -> None:
        report = ElementTreeValidator().validate_tree(
            [_Leaf("a", (_error("a"),)), _Leaf("b", (_error("b"),))],
        )
        assert len(report) == 2
        ids = {err.element_id for err in report.errors}
        assert ids == {"a", "b"}

    def test_walk_recurses_into_children(self) -> None:
        tree = [_Container((_Leaf("deep", (_error("deep"),)),))]
        report = ElementTreeValidator().validate_tree(tree)
        assert len(report) == 1
        assert report.errors[0].element_id == "deep"

    def test_walk_collects_across_the_hierarchy(self) -> None:
        # A bad leaf and a good leaf under one container: only the bad one errors.
        tree = [_Container((_Leaf("bad", (_error("bad"),)), _Leaf("good", ())))]
        report = ElementTreeValidator().validate_tree(tree)
        assert len(report) == 1
        assert report.errors[0].element_id == "bad"

    def test_inert_element_contributes_nothing(self) -> None:
        report = ElementTreeValidator().validate_tree([_Inert()])
        assert report.ok
