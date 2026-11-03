"""SetterPriority: which patch keys a kind's setters run first, and its validation."""

from __future__ import annotations

import pytest

from punt_lux.domain.setter_priority import SetterPriority


class _WithSetters:
    def _set_a(self, value: object) -> None: ...

    def _set_b(self, value: object) -> None: ...


def test_the_priority_keys_come_first_in_their_own_order() -> None:
    patch: dict[str, object] = {"x": 1, "b": 2, "y": 3, "a": 4}

    ordered = SetterPriority(("a", "b")).arrange(patch)

    assert list(ordered) == ["a", "b", "x", "y"]


def test_arranging_keeps_every_key_and_value_of_the_patch() -> None:
    patch: dict[str, object] = {"x": 1, "b": 2, "a": 3}

    assert SetterPriority(("a", "b")).arrange(patch) == patch


def test_a_priority_key_the_patch_lacks_is_skipped() -> None:
    patch: dict[str, object] = {"x": 1}

    assert list(SetterPriority(("a",)).arrange(patch)) == ["x"]


def test_no_priority_keeps_the_callers_order() -> None:
    patch: dict[str, object] = {"y": 1, "x": 2}

    assert list(SetterPriority(()).arrange(patch)) == ["y", "x"]


def test_a_kind_with_a_setter_for_every_priority_key_is_accepted() -> None:
    SetterPriority(("a", "b")).require_setters(_WithSetters)


def test_a_kind_naming_a_key_it_has_no_setter_for_is_refused() -> None:
    with pytest.raises(TypeError, match=r"_WithSetters.*\['c'\]"):
        SetterPriority(("a", "c")).require_setters(_WithSetters)
