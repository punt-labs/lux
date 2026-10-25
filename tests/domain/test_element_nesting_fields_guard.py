"""Every element declares exactly the fields whose type can hold nested elements.

``Element.NESTING_FIELDS`` is what lets an update skip the nesting projection when
no patched field can deepen the tree. The declaration is hand-written on the
element; this guard derives the same answer from the element's own property
annotations, so a new structural field that is not declared fails here, naming
the class and the field.
"""

from __future__ import annotations

import dataclasses
import importlib
import sys
import types
from dataclasses import dataclass
from typing import ClassVar, cast, get_args, get_origin, get_type_hints

import pytest

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements import TextElement, TreeElement, WindowElement

_SETTER_PREFIX = "_set_"


class _Derivation:
    """What an element class's annotations say can hold nested elements."""

    @classmethod
    def fields_of(cls, element_type: type) -> frozenset[str]:
        patchable = (
            name.removeprefix(_SETTER_PREFIX)
            for name in dir(element_type)
            if name.startswith(_SETTER_PREFIX)
        )
        return frozenset(f for f in patchable if cls._holds_elements(element_type, f))

    @classmethod
    def _holds_elements(cls, element_type: type, field: str) -> bool:
        prop = getattr(element_type, field, None)
        assert isinstance(prop, property) and prop.fget is not None, (
            f"{element_type.__name__}.{field} is patchable but has no property to "
            "read its type from"
        )
        hints = get_type_hints(prop.fget, localns=cls._siblings(prop.fget.__module__))
        assert "return" in hints, (
            f"{element_type.__name__}.{field} property has no return annotation"
        )
        return cls._can_contain(hints["return"], ())

    @classmethod
    def _can_contain(cls, declared: object, path: tuple[type, ...]) -> bool:
        if get_origin(declared) is not None or isinstance(declared, types.UnionType):
            return any(cls._can_contain(arg, path) for arg in get_args(declared))
        if not isinstance(declared, type):
            return False
        if issubclass(declared, Element) or declared in path:
            return True
        if not dataclasses.is_dataclass(declared):
            return False
        hints = get_type_hints(declared, localns=cls._siblings(declared.__module__))
        return any(cls._can_contain(h, (*path, declared)) for h in hints.values())

    @staticmethod
    def _siblings(module_name: str) -> dict[str, object]:
        """Classes of the module's package, for names imported only to type-check."""
        package = module_name.rpartition(".")[0]
        own = vars(sys.modules[module_name])
        found: dict[str, object] = {}
        for name, module in list(sys.modules.items()):
            if name != package and not name.startswith(f"{package}."):
                continue
            for member, value in list(vars(module).items()):
                if isinstance(value, type) and member not in own:
                    found.setdefault(member, value)
        return found

    @staticmethod
    def _declared(element_type: type) -> frozenset[str]:
        return cast("type[Element]", element_type).NESTING_FIELDS

    @classmethod
    def undeclared(cls, element_type: type) -> frozenset[str]:
        """Return the derived fields ``element_type`` does not declare."""
        return cls.fields_of(element_type) - cls._declared(element_type)

    @classmethod
    def overdeclared(cls, element_type: type) -> frozenset[str]:
        """Return the declared fields the annotations do not support."""
        return cls._declared(element_type) - cls.fields_of(element_type)


def _kinds() -> list[type]:
    importlib.import_module("punt_lux.protocol.elements.abc_registry")  # every kind
    found: dict[str, type] = {}
    pending = list(Element.__subclasses__())
    while pending:
        kind = pending.pop()
        pending.extend(kind.__subclasses__())
        if kind.__module__.startswith("punt_lux."):
            found[kind.__qualname__] = kind
    return sorted(found.values(), key=lambda k: k.__qualname__)


@pytest.mark.parametrize("kind", _kinds(), ids=lambda k: k.__name__)
def test_every_kind_declares_what_its_annotations_say_can_nest(
    kind: type,
) -> None:
    assert not _Derivation.undeclared(kind), (
        f"{kind.__name__} has fields that can hold elements but are not in "
        f"NESTING_FIELDS: {sorted(_Derivation.undeclared(kind))}"
    )
    assert not _Derivation.overdeclared(kind), (
        f"{kind.__name__}.NESTING_FIELDS names fields no annotation supports: "
        f"{sorted(_Derivation.overdeclared(kind))}"
    )


def test_the_guard_covers_the_kinds_that_matter() -> None:
    assert {TextElement, TreeElement, WindowElement} <= set(_kinds())


def test_a_tree_declares_its_nodes() -> None:
    assert frozenset({"nodes"}) == TreeElement.NESTING_FIELDS


def test_a_text_element_declares_nothing() -> None:
    assert frozenset() == TextElement.NESTING_FIELDS


class _Pane(Element):
    """Planted: ``panes`` holds elements and is not declared; ``title`` is text."""

    @property
    def panes(self) -> tuple[Element, ...]:
        return ()

    @property
    def title(self) -> str:
        return ""

    def _set_panes(self, value: object) -> None: ...

    def _set_title(self, value: object) -> None: ...


@dataclass(frozen=True)
class _Branch:
    branches: tuple[_Branch, ...] = ()


class _Forest(Element):
    """Planted: a self-referential value class, declared correctly."""

    NESTING_FIELDS: ClassVar[frozenset[str]] = frozenset({"roots", "ghost"})

    @property
    def roots(self) -> tuple[_Branch, ...]:
        return ()

    @property
    def note(self) -> str | None:
        return None

    @property
    def ghost(self) -> str:
        return ""

    def _set_roots(self, value: object) -> None: ...

    def _set_note(self, value: object) -> None: ...

    def _set_ghost(self, value: object) -> None: ...


class TestThePlantedCasesAreCaught:
    def test_an_undeclared_structural_field_is_found(self) -> None:
        assert _Derivation.undeclared(_Pane) == frozenset({"panes"})

    def test_a_scalar_field_beside_it_is_not_flagged(self) -> None:
        assert "title" not in _Derivation.fields_of(_Pane)

    def test_a_self_referential_value_class_counts_as_nested_content(self) -> None:
        assert "roots" in _Derivation.fields_of(_Forest)

    def test_an_optional_scalar_is_not_nested_content(self) -> None:
        assert "note" not in _Derivation.fields_of(_Forest)

    def test_a_declared_field_no_annotation_supports_is_found(self) -> None:
        assert _Derivation.overdeclared(_Forest) == frozenset({"ghost"})

    def test_the_guard_message_would_name_the_class_and_field(self) -> None:
        with pytest.raises(AssertionError, match=r"_Pane.*panes"):
            assert not _Derivation.undeclared(_Pane), (
                f"{_Pane.__name__} has fields that can hold elements but are not "
                f"in NESTING_FIELDS: {sorted(_Derivation.undeclared(_Pane))}"
            )
