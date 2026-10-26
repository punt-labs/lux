"""An element checkpoint puts back every kind exactly; its setters keep that true.

The checkpoint is a shallow copy of an element's fields, which is the whole state only
while every ``_set_*`` replaces a field and never mutates one in place. The guard here
scans every setter in the source for the in-place forms, and every kind is restored
from a checkpoint taken before its fields were broken.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import pytest

from punt_lux.domain.element_abc import Element
from punt_lux.domain.element_checkpoint import ElementCheckpoint
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from tests.conftest import _build_test_factory

if TYPE_CHECKING:
    from collections.abc import Mapping

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"
_REQUIRED: dict[str, dict[str, object]] = {
    "image": {"path": "x.png"},
    "markdown": {"content": "m"},
    "progress": {"fraction": 0.5},
    "text": {"content": "t"},
}
_MUTATORS = {
    "append",
    "extend",
    "insert",
    "remove",
    "pop",
    "clear",
    "update",
    "add",
    "discard",
    "sort",
    "reverse",
    "setdefault",
    "popitem",
}


def _kinds() -> list[str]:
    return sorted(DEFAULT_ABC_REGISTRY.all_kinds)


@pytest.mark.parametrize("kind", _kinds())
def test_every_kind_is_restored_field_for_field(kind: str) -> None:
    raw: Mapping[str, object] = {"kind": kind, "id": "e", **_REQUIRED.get(kind, {})}
    element = _build_test_factory().decode(raw)
    before = dict(vars(element))
    checkpoint = ElementCheckpoint(element)

    fields = vars(element)
    for name in before:
        fields[name] = object()  # every field broken
    fields["_stray"] = object()  # and one the checkpoint never saw
    checkpoint.restore()

    assert vars(element).keys() == before.keys()
    assert all(vars(element)[name] is value for name, value in before.items())


def _in_place_writes(source: str) -> list[str]:
    """Each statement of a ``_set_*`` method that mutates ``self._x`` in place."""
    found: list[str] = []
    for method in ast.walk(ast.parse(source)):
        if not (
            isinstance(method, ast.FunctionDef) and method.name.startswith("_set_")
        ):
            continue
        for node in ast.walk(method):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _MUTATORS
                and ast.unparse(node.func.value).startswith("self._")
            ):
                found.append(f"{method.name}: {ast.unparse(node)}")
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AugAssign | ast.AnnAssign)
                else []
            )
            found.extend(
                f"{method.name}: {ast.unparse(node)}"
                for target in targets
                if isinstance(target, ast.Subscript)
                and ast.unparse(target.value).startswith("self._")
            )
    return found


def test_no_setter_in_the_source_mutates_a_field_in_place() -> None:
    found = {
        path.relative_to(_SRC).as_posix(): writes
        for path in sorted(_SRC.rglob("*.py"))
        if (writes := _in_place_writes(path.read_text("utf-8")))
    }

    assert found == {}


@pytest.mark.parametrize(
    "planted",
    [
        "class K:\n    def _set_items(self, v):\n        self._items.append(v)\n",
        "class K:\n    def _set_items(self, v):\n        self._items[0] = v\n",
        (
            "class K:\n    def _set_items(self, v):\n        self._items |= v\n"
            "        self._seen[0] = v\n"
        ),
    ],
)
def test_the_scan_sees_a_planted_in_place_write(planted: str) -> None:
    assert _in_place_writes(planted) != []


def test_the_scan_leaves_a_replacing_setter_alone() -> None:
    planted = "class K:\n    def _set_items(self, v):\n        self._items = tuple(v)\n"

    assert _in_place_writes(planted) == []


def _define_a_kind_with_priority(priority: tuple[str, ...]) -> type[Element]:
    """Define a kind with no setters, whose ``_SETTER_PRIORITY`` is ``priority``."""
    return type("_Kind", (Element,), {"_SETTER_PRIORITY": priority})


class TestASetterPriorityNamesOnlyKeysWithSetters:
    def test_a_misspelt_key_is_refused_when_the_kind_is_defined(self) -> None:
        with pytest.raises(TypeError, match=r"selected_node_id.*_set_<key>"):
            _define_a_kind_with_priority(("selected_node_id",))

    def test_a_key_with_a_setter_is_accepted(self) -> None:
        class _Good(Element):
            _SETTER_PRIORITY: ClassVar[tuple[str, ...]] = ("label",)

            def _set_label(self, value: object) -> None:
                self._label = value

        assert _Good._SETTER_PRIORITY == ("label",)
