"""Every kind's final state is judged by its own ``validate()``, before observers.

A handler or an observer writes through ``apply_patch``, which never ran the kind's
``validate()``: only the agent's path did. The final-state hook now derives from
``validate()`` for every kind, so one rule answers on both paths. The kinds come from
the element registry, not from a list typed by hand, so a new kind is covered the day
it is registered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements import (
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    ImageElement,
    InputNumberElement,
    MarkdownElement,
    RadioElement,
    SliderElement,
    TableElement,
    TextElement,
)
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.element_abc import Element

# Kinds that cannot be built from an id alone.
_NEEDS: dict[type, dict[str, object]] = {
    CollapsingHeaderElement: {"label": "x"},
    TextElement: {"content": "x"},
    MarkdownElement: {"content": "x"},
    ImageElement: {"path": "x.png"},
}

_KINDS = [(spec.kind, spec.element_type) for spec in DEFAULT_ABC_REGISTRY.specs]


def _built(kind: type) -> Element:
    return kind(id="e", **_NEEDS.get(kind, {}))  # type: ignore[no-any-return]  # per kind


def test_the_registry_is_the_source_of_the_kinds_under_test() -> None:
    assert {name for name, _ in _KINDS} == DEFAULT_ABC_REGISTRY.all_kinds
    assert len(_KINDS) == len(DEFAULT_ABC_REGISTRY.abc_types)


@pytest.mark.parametrize(("name", "kind"), _KINDS, ids=[n for n, _ in _KINDS])
def test_a_kind_whose_validate_reports_is_refused_before_an_observer_hears_it(
    monkeypatch: pytest.MonkeyPatch, name: str, kind: type
) -> None:
    def invalid(self: Element) -> tuple[ValidationError, ...]:
        return (ValidationError(self.id, name, f"{name} is invalid now"),)

    monkeypatch.setattr(kind, "validate", invalid)
    element = _built(kind)
    heard: list[str] = []
    element.add_observer(heard.append)

    with pytest.raises(ValueError, match=f"{name} is invalid now"):
        element.apply_patch({})

    assert heard == []


@pytest.mark.parametrize(("name", "kind"), _KINDS, ids=[n for n, _ in _KINDS])
def test_a_kind_whose_validate_is_clean_takes_an_empty_patch(
    name: str, kind: type
) -> None:
    element = _built(kind)

    assert element.validate() == ()
    assert element.apply_patch({}) is element


# One patch per kind that can be invalidated by a write, and how to build it.
_INVALIDATING: list[tuple[Callable[[], Element], dict[str, object]]] = [
    (lambda: SliderElement(id="e", value=1.0), {"value": 999.0}),
    (lambda: RadioElement(id="e", items=["a", "b"]), {"selected": 9}),
    (lambda: ComboElement(id="e", items=["a", "b"]), {"selected": 9}),
    (
        lambda: InputNumberElement(id="e", value=1.0, min=0.0, max=10.0),
        {"value": 99.0},
    ),
    (
        lambda: TableElement(id="e", columns=["a", "b"], rows=[["x", "y"]]),
        {"columns": ["a", "b", "c"]},
    ),
    (lambda: ColorPickerElement(id="e"), {"value": "red"}),
]


@pytest.mark.parametrize(
    ("make", "patch"),
    _INVALIDATING,
    ids=["slider", "radio", "combo", "input_number", "table", "color_picker"],
)
def test_a_write_that_leaves_the_kind_invalid_is_refused_and_leaves_it_as_it_was(
    make: Callable[[], Element], patch: dict[str, object]
) -> None:
    element = make()
    before = {k: v for k, v in vars(element).items() if k != "_observers"}
    heard: list[str] = []
    element.add_observer(heard.append)

    with pytest.raises(ValueError):
        element.apply_patch(patch)

    assert heard == []
    assert {k: v for k, v in vars(element).items() if k != "_observers"} == before
