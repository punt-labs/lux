"""Where an element is patched, and which fields each Hub handler may patch.

Every write a Hub-side handler makes is judged at run time: the write seam fires the
event inside the judge's scope (``tests/domain/test_handler_writes_are_judged.py``), so
the nesting cap holds whatever a handler patches. This module pins what that relies on
and what it does not cover:

- the seam is the one Hub-side door an element's event is fired through, so no handler
  runs outside the judge (``TestOnlyTheSeamFiresAnEventOnTheHub``);
- every reference to ``apply_patch`` in the package, called or not, is the seam's, the
  display's own replica's, an element's override, or a handler on the closed list below;
- each handler on that list patches only fields whose setters refuse a deeper value,
  as a second line behind the judge: a literal dict of constant keys, or the one
  computed key pinned to two scalar fields.

A write that does not go through ``apply_patch`` (another verb on an element) is not
what this module reads.
"""

from __future__ import annotations

import ast
import typing
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import pytest

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.value_change_handlers import ChangedField

if TYPE_CHECKING:
    from collections.abc import Mapping

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"

# Callers that are not a handler: the seam and its realization, the display's own
# replica of what the Hub sent (never the Hub's store), and elements' own overrides.
_SEAM = frozenset({"domain/hub/field_realization.py", "domain/hub/write_seam.py"})
_DISPLAY_REPLICA = frozenset({"display/replica/element_walk.py"})

# The handlers that patch the Hub's copy of an element, with the fields each patches.
# ``rows`` is a re-projection of rows already in the element, a subset that cannot nest
# deeper; ``content`` is the card text a detail region was installed with.
_HANDLERS: dict[str, frozenset[str]] = {
    "protocol/compositions/filtered_table_model.py": frozenset(
        {"rows", "selected_row_ids"}
    ),
    "protocol/compositions/table_selection_handlers.py": frozenset({"content"}),
    "protocol/elements/collapsing_header_codec.py": frozenset({"open"}),
    "protocol/elements/color_picker_codec.py": frozenset({"value"}),
    "protocol/elements/input_number_codec.py": frozenset({"value"}),
    "protocol/elements/input_text_codec.py": frozenset({"value"}),
    "protocol/elements/slider_codec.py": frozenset({"value"}),
    "protocol/elements/tab_bar_codec.py": frozenset({"active_tab"}),
    "protocol/elements/table_codec.py": frozenset(
        {"selected_row_ids", "anchor_row_id"}
    ),
    "protocol/elements/value_change_handlers.py": frozenset(),  # a Literal field
}


# The one handler whose key is computed: ``self._field``, typed ``ChangedField``, which
# ``test_the_one_dynamic_field_is_a_closed_pair_of_scalars`` pins to two scalar fields.
_CLOSED_KEY = {"protocol/elements/value_change_handlers.py": "self._field"}


@cache
def _parsed(source: str) -> ast.Module:
    """One parse per source, so a node found twice is the same object."""
    return ast.parse(source)


def _patch_references(source: str) -> list[ast.Attribute]:
    """Every ``<receiver>.apply_patch`` in ``source``, called or not, bar ``super()``'s.

    A bound method held in a name or a field and called later is the same write, so
    the reference is what counts, not the call.
    """
    return [
        node
        for node in ast.walk(_parsed(source))
        if isinstance(node, ast.Attribute)
        and node.attr == "apply_patch"
        and not (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "super"
        )
    ]


def _called_directly(source: str) -> set[int]:
    """The ``id`` of every ``apply_patch`` reference called where it is named."""
    return {
        id(node.func)
        for node in ast.walk(_parsed(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "apply_patch"
    }


def _patch_calls(source: str) -> list[ast.Call]:
    """The ``<receiver>.apply_patch(...)`` calls in ``source``, bar ``super()``'s."""
    references = {id(node) for node in _patch_references(source)}
    return [
        node
        for node in ast.walk(_parsed(source))
        if isinstance(node, ast.Call) and id(node.func) in references
    ]


def _patched_fields(call: ast.Call, module: str = "") -> frozenset[str] | None:
    """The field names a call's literal patch names; ``None`` when unproven.

    Only a dict literal with constant string keys names its fields. A patch held in
    a variable, built by ``dict(...)``, or spread with ``**`` could carry any field,
    so the guard cannot vouch for it.
    """
    if not call.args or not isinstance(call.args[0], ast.Dict):
        return None
    keys = [
        key
        for key in call.args[0].keys
        if not (key is not None and ast.unparse(key) == _CLOSED_KEY.get(module))
    ]
    if not all(
        isinstance(key, ast.Constant) and isinstance(key.value, str) for key in keys
    ):
        return None
    return frozenset(
        key.value
        for key in keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    )


def _callers(source_by_module: dict[str, str]) -> dict[str, list[ast.Attribute]]:
    """The modules that mention ``apply_patch``, and each mention."""
    return {
        module: references
        for module, source in source_by_module.items()
        if (references := _patch_references(source))
    }


def _sources() -> dict[str, str]:
    return {
        path.relative_to(_SRC).as_posix(): path.read_text(encoding="utf-8")
        for path in _SRC.rglob("*.py")
    }


def _unaccounted(source_by_module: dict[str, str]) -> list[str]:
    """Modules that patch an element and are not the seam, the replica or listed."""
    known = _SEAM | _DISPLAY_REPLICA | frozenset(_HANDLERS)
    return sorted(set(_callers(source_by_module)) - known)


def _beyond_the_list(source_by_module: dict[str, str]) -> list[str]:
    """Handlers that patch a field their list entry does not vouch for."""
    found: list[str] = []
    for module, references in _callers(source_by_module).items():
        if module not in _HANDLERS:
            continue
        source = source_by_module[module]
        direct = _called_directly(source)
        calls = {id(call.func): call for call in _patch_calls(source)}
        for reference in references:
            if id(reference) not in direct:
                found.append(f"{module}: a reference that is not called where named")
                continue
            fields = _patched_fields(calls[id(reference)], module)
            if fields is None:
                found.append(f"{module}: a patch whose fields are not a literal")
            elif extra := fields - _HANDLERS[module]:
                found.append(f"{module}: {sorted(extra)}")
    return found


class TestEveryPatchOfAnElementIsAccountedFor:
    def test_the_package_patches_elements_only_in_the_places_listed(self) -> None:
        assert _unaccounted(_sources()) == []

    def test_each_handler_patches_only_the_fields_its_entry_vouches_for(self) -> None:
        assert _beyond_the_list(_sources()) == []

    def test_every_listed_handler_still_patches(self) -> None:
        patching = set(_callers(_sources()))

        assert set(_HANDLERS) <= patching, "a listed handler no longer writes"

    def test_the_one_dynamic_field_is_a_closed_pair_of_scalars(self) -> None:
        assert typing.get_args(ChangedField.__value__) == ("value", "selected")

    def test_a_planted_new_handler_is_found(self) -> None:
        planted = {
            "protocol/elements/new_codec.py": (
                "class H:\n    def __call__(self, e):\n"
                "        self._elem.apply_patch({'nodes': e.nodes})\n"
            )
        }

        assert _unaccounted(planted) == ["protocol/elements/new_codec.py"]

    def test_a_planted_listed_handler_that_patches_a_new_field_is_found(self) -> None:
        planted = {
            "protocol/elements/slider_codec.py": (
                "class H:\n    def __call__(self, e):\n"
                "        self._elem.apply_patch({'value': e.value, 'nodes': e.n})\n"
            )
        }

        assert _beyond_the_list(planted) == [
            "protocol/elements/slider_codec.py: ['nodes']"
        ]

    @pytest.mark.parametrize(
        "patch",
        ["patch", "dict(value=e.value)", "{**e.fields}", "{e.name: e.value}"],
        ids=["bound-name", "dict-call", "spread", "computed-key"],
    )
    def test_a_planted_handler_whose_patch_is_not_a_literal_is_unproven(
        self, patch: str
    ) -> None:
        planted = {
            "protocol/elements/slider_codec.py": (
                "class H:\n    def __call__(self, e):\n"
                f"        patch = {{'nodes': e.n}}\n"
                f"        self._elem.apply_patch({patch})\n"
            )
        }

        assert _beyond_the_list(planted) == [
            "protocol/elements/slider_codec.py: a patch whose fields are not a literal"
        ]

    @pytest.mark.parametrize(
        "planted",
        [
            "patch = self._elem.apply_patch\n        patch({'nodes': e.n})",
            "self._write = self._elem.apply_patch\n        self._write({'nodes': e.n})",
            "run(self._elem.apply_patch, {'nodes': e.n})",
        ],
        ids=["bound-name", "stored-field", "passed-on"],
    )
    def test_a_bound_apply_patch_in_a_listed_handler_is_unproven(
        self, planted: str
    ) -> None:
        source = {
            "protocol/elements/slider_codec.py": (
                f"class H:\n    def __call__(self, e):\n        {planted}\n"
            )
        }

        assert _beyond_the_list(source) == [
            (
                "protocol/elements/slider_codec.py: "
                "a reference that is not called where named"
            )
        ]

    def test_a_bound_apply_patch_in_an_unlisted_module_is_found(self) -> None:
        planted = {
            "protocol/elements/new_codec.py": (
                "class H:\n    def __init__(self, elem):\n"
                "        self._write = elem.apply_patch\n"
                "    def __call__(self, e):\n"
                "        self._write({'nodes': e.n})\n"
            )
        }

        assert _unaccounted(planted) == ["protocol/elements/new_codec.py"]

    def test_a_super_call_in_an_override_is_not_a_patch_site(self) -> None:
        planted = (
            "class S:\n    def apply_patch(self, p):\n        super().apply_patch(p)\n"
        )

        assert _patch_calls(planted) == []
        assert _patch_references(planted) == []


def _fires_in(source: str) -> list[str]:
    """Every ``<x>.fire`` the source names, called or not, as it is spelled."""
    return [
        ast.unparse(node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr == "fire"
    ]


def _fires_outside_a_judged_scope(source: str) -> list[str]:
    """Every ``<x>.fire`` named outside the argument of a ``<x>.run_handler(...)``.

    ``BatchTransaction.run_handler`` runs its argument under the judge, and undoes
    every write the handler made when one is refused.
    """
    tree = ast.parse(source)
    judged: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run_handler"
        ):
            judged.update(id(inner) for arg in node.args for inner in ast.walk(arg))
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "fire"
        and id(node) not in judged
    ]


class TestOnlyAJudgedInteractionFiresAnEventOnTheHub:
    """The one element fire on the Hub runs inside the judge; no handler escapes it."""

    def test_the_hub_fires_an_element_only_through_a_resolved_interaction(
        self,
    ) -> None:
        firing = {
            module: names
            for module, source in _sources().items()
            if not module.startswith("display/") and (names := _fires_in(source))
        }

        assert firing == {
            "domain/hub/element_invocation_resolver.py": ["self.element.fire"],
            "domain/hub/hub_interaction_dispatch.py": ["resolved.fire"],
            "domain/hub/departure_cascade.py": ["self._sinks.fire"],  # not an element
        }

    def test_that_fire_runs_inside_the_judged_scope(self) -> None:
        source = _sources()["domain/hub/element_invocation_resolver.py"]

        assert _fires_outside_a_judged_scope(source) == []

    def test_a_fire_outside_the_scope_is_found(self) -> None:
        planted = "def f(element, event):\n    element.fire(event)\n"

        assert _fires_outside_a_judged_scope(planted) == ["element.fire"]

    def test_a_fire_inside_the_scope_is_not_flagged(self) -> None:
        planted = (
            "def f(element, event, transaction):\n"
            "    transaction.run_handler(lambda: element.fire(event))\n"
        )

        assert _fires_outside_a_judged_scope(planted) == []

    @pytest.mark.parametrize(
        "planted",
        [
            "element.fire(event)",
            "send = element.fire\n    send(event)",
            "self._fire = element.fire",
        ],
        ids=["called", "bound-name", "stored-field"],
    )
    def test_every_way_of_naming_a_fire_is_found(self, planted: str) -> None:
        names = _fires_in(f"def f(element, event):\n    {planted}\n")

        assert names == ["element.fire"]


def _deep() -> object:
    value: object = []
    for _ in range(100):
        value = [value]
    return value


class _PatchableWire(WireElement, Protocol):
    """An element with a wire form that a patch can be applied to."""

    def apply_patch(self, patch: Mapping[str, object]) -> object:
        """Apply ``patch`` in place."""
        ...


_SCALAR_FIELDS: list[tuple[str, _PatchableWire, str]] = [
    ("slider", SliderElement(id="e"), "value"),
    ("input_number", InputNumberElement(id="e"), "value"),
    ("input_text", InputTextElement(id="e"), "value"),
    ("color_picker", ColorPickerElement(id="e"), "value"),
    ("checkbox", CheckboxElement(id="e"), "value"),
    ("combo", ComboElement(id="e", items=["a"]), "selected"),
    ("radio", RadioElement(id="e", items=["a"]), "selected"),
    ("selectable", SelectableElement(id="e"), "selected"),
    ("collapsing_header", CollapsingHeaderElement(id="e"), "open"),
    ("tab_bar", TabBarElement(id="e"), "active_tab"),
    ("table", TableElement(id="e", columns=["c"], rows=[["r"]]), "selected_row_ids"),
    ("table", TableElement(id="e", columns=["c"], rows=[["r"]]), "anchor_row_id"),
]


class TestAHandlerWriteCannotDeepenTheWireForm:
    @pytest.mark.parametrize(
        ("kind", "element", "field"),
        _SCALAR_FIELDS,
        ids=[f"{kind}.{field}" for kind, _e, field in _SCALAR_FIELDS],
    )
    def test_the_field_refuses_a_value_that_is_not_a_scalar(
        self, kind: str, element: _PatchableWire, field: str
    ) -> None:
        before = NestingCap().depth(element)

        with pytest.raises((TypeError, ValueError)):
            element.apply_patch({field: _deep()})

        assert NestingCap().depth(element) == before
