"""Container self-validation contract: child exposure, tree structure, guard.

Every container element kind must expose its children to the validation
walk so a malformed element nested inside it is caught rather than
rendered unchecked. The structural guards at the bottom fail if a *new*
container kind is added without a ``child_elements`` method (presence) or
whose element children do not actually surface (behavior) — turning the
"hope none are missed" shape into an enforced contract.
"""

from __future__ import annotations

import dataclasses
from typing import cast, get_args

import pytest

from punt_lux.domain.validation_walk import HasChildElements
from punt_lux.protocol.elements import Element
from punt_lux.protocol.elements.layout import (
    CollapsingHeaderElement,
    ModalElement,
    TabBarElement,
    TreeElement,
    WindowElement,
)
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.text import TextElement


class TestContainerChildElements:
    def test_window_exposes_children(self) -> None:
        child = TextElement(id="t", content="x")
        window = WindowElement(id="w", children=[child])
        assert window.child_elements() == (child,)

    def test_collapsing_header_exposes_children(self) -> None:
        child = TextElement(id="t", content="x")
        header = CollapsingHeaderElement(id="ch", children=[child])
        assert header.child_elements() == (child,)

    def test_modal_exposes_children(self) -> None:
        child = TextElement(id="t", content="x")
        modal = ModalElement(id="m", children=[child])
        assert modal.child_elements() == (child,)

    def test_tab_bar_exposes_every_tab_child(self) -> None:
        a = TextElement(id="a", content="x")
        b = TableElement(id="b", columns=["A"], rows=[["y"]])
        tab_bar = TabBarElement(
            id="tb",
            tabs=[
                {"label": "One", "children": [a]},
                {"label": "Two", "children": [b]},
            ],
        )
        assert tab_bar.child_elements() == (a, b)

    def test_empty_containers_have_no_children(self) -> None:
        assert WindowElement(id="w").child_elements() == ()
        assert CollapsingHeaderElement(id="ch").child_elements() == ()
        assert ModalElement(id="m").child_elements() == ()
        assert TabBarElement(id="tb").child_elements() == ()

    def test_tree_exposes_no_child_elements(self) -> None:
        # A tree's nodes are plain mappings, not elements; the tree checks
        # its own node structure in validate() rather than via the walk.
        tree = TreeElement(id="tr", nodes=[{"label": "root"}])
        assert tree.child_elements() == ()


class TestTreeValidate:
    def test_well_formed_tree_has_no_errors(self) -> None:
        tree = TreeElement(
            id="files",
            nodes=[
                {"label": "src", "children": [{"label": "main.py"}]},
                {"label": "README.md"},
            ],
        )
        assert tree.validate() == ()

    def test_empty_tree_is_valid(self) -> None:
        assert TreeElement(id="files").validate() == ()

    def test_non_mapping_node_is_reported(self) -> None:
        tree = TreeElement(id="files", nodes=[42])  # type: ignore[list-item]  # deliberately malformed
        errors = tree.validate()
        assert len(errors) == 1
        assert errors[0].element_kind == "tree"
        assert errors[0].element_id == "files"
        assert "node 0 is not a mapping" in errors[0].message

    def test_node_missing_label_is_reported(self) -> None:
        tree = TreeElement(id="files", nodes=[{"note": "no label here"}])
        errors = tree.validate()
        assert len(errors) == 1
        assert "missing a string 'label'" in errors[0].message

    def test_malformed_child_node_is_reported(self) -> None:
        tree = TreeElement(
            id="files",
            nodes=[{"label": "root", "children": [42]}],  # malformed grandchild
        )
        errors = tree.validate()
        assert len(errors) == 1
        assert "is not a mapping" in errors[0].message

    def test_non_list_nodes_is_reported(self) -> None:
        tree = TreeElement(id="files", nodes="oops")  # type: ignore[arg-type]  # deliberately malformed
        errors = tree.validate()
        assert len(errors) == 1
        assert "nodes must be a list of nodes" in errors[0].message

    def test_every_malformed_node_collects_at_once(self) -> None:
        tree = TreeElement(
            id="files",
            nodes=[42, {"note": "no label"}],  # type: ignore[list-item]  # deliberately malformed
        )
        errors = tree.validate()
        assert len(errors) == 2


_CHILD_BEARING_FIELDS = frozenset({"children", "tabs", "nodes", "pages"})


def _container_element_classes() -> list[type]:
    """Derive the container kinds structurally from the Element union.

    A kind is a container if it is a dataclass carrying any child-bearing
    field. Deriving from the union (not a hand-maintained list) means a
    new container kind is picked up automatically — and fails the contract
    test below if it forgets ``child_elements``.
    """
    classes: list[type] = []
    for cls in get_args(Element):
        if not isinstance(cls, type) or not dataclasses.is_dataclass(cls):
            continue
        field_names = {f.name for f in dataclasses.fields(cls)}
        if field_names & _CHILD_BEARING_FIELDS:
            classes.append(cls)
    return classes


_ELEMENT_CHILD_FIELDS = frozenset({"children", "tabs", "pages"})


def _element_child_container_classes() -> list[type]:
    """Containers whose children are Lux elements, not mapping nodes.

    ``TreeElement`` carries only ``nodes`` (plain mappings) and legitimately
    exposes no child elements, so it is excluded from the behavioral guard.
    """
    return [
        cls
        for cls in _container_element_classes()
        if {f.name for f in dataclasses.fields(cls)} & _ELEMENT_CHILD_FIELDS
    ]


def _construct_with_child(cls: type, child: object) -> HasChildElements:
    """Build ``cls`` with ``child`` planted in whichever child field it has."""
    field_names = {f.name for f in dataclasses.fields(cls)}
    factory = cast("type[HasChildElements]", cls)
    if "children" in field_names:
        made = factory(id="c", children=[child])  # type: ignore[call-arg]  # dataclass kwargs
    elif "tabs" in field_names:
        made = factory(id="c", tabs=[{"label": "t", "children": [child]}])  # type: ignore[call-arg]  # dataclass kwargs
    elif "pages" in field_names:
        made = factory(id="c", pages=[[child]])  # type: ignore[call-arg]  # dataclass kwargs
    else:  # pragma: no cover - guarded by the derivation
        pytest.fail(f"no known element-child field for {cls.__name__}")
    return made


class TestContainerContract:
    def test_derivation_finds_the_known_containers(self) -> None:
        found = set(_container_element_classes())
        expected = {
            WindowElement,
            CollapsingHeaderElement,
            ModalElement,
            TabBarElement,
            TreeElement,
        }
        assert expected <= found

    @pytest.mark.parametrize("cls", _container_element_classes())
    def test_every_container_kind_exposes_child_elements(self, cls: type) -> None:
        assert issubclass(cls, HasChildElements)

    @pytest.mark.parametrize("cls", _element_child_container_classes())
    def test_element_child_container_actually_surfaces_its_child(
        self,
        cls: type,
    ) -> None:
        # Presence of child_elements() is not enough — a method that wrongly
        # returned () would pass the isinstance guard while hiding its subtree.
        # Plant a child and assert the walk-facing method actually surfaces it.
        child = TextElement(id="planted", content="x")
        container = _construct_with_child(cls, child)
        assert child in container.child_elements()
