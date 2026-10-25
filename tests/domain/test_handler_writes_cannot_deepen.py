"""Every write to an element reaches the nesting cap, or provably cannot deepen it.

A write an agent makes goes through :class:`~punt_lux.domain.hub.write_seam.WriteSeam`,
which judges the cap. A Hub-side handler also writes: when the display reports a click
or an edit, the handler patches the Hub's own copy of the element, and nothing judges
that write. It does not need judging, because what it writes is scalar by construction:
the event's value is a ``bool | int | float | str``, a row selection is a tuple of ids,
and an element's setter refuses anything else. A new handler that patched a container
field would break that, so the guard reads every ``apply_patch`` call in the package:
a caller is the seam, the display's own replica, an element's override of the method,
or a handler on the closed list below, and each handler on it patches only the fields
proven here to refuse a deeper value.
"""

from __future__ import annotations

import ast
import typing
from pathlib import Path

import pytest

from punt_lux.domain.element_abc import Element
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


def _patch_calls(source: str) -> list[ast.Call]:
    """The ``<receiver>.apply_patch(...)`` calls in ``source``, bar ``super()``'s."""
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "apply_patch"
        and not (
            isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        )
    ]


def _patched_fields(call: ast.Call) -> frozenset[str]:
    """The constant field names a call's literal patch names."""
    if not call.args or not isinstance(call.args[0], ast.Dict):
        return frozenset()
    return frozenset(
        key.value
        for key in call.args[0].keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    )


def _callers(source_by_module: dict[str, str]) -> dict[str, list[ast.Call]]:
    return {
        module: calls
        for module, source in source_by_module.items()
        if (calls := _patch_calls(source))
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
    for module, calls in _callers(source_by_module).items():
        if module not in _HANDLERS:
            continue
        for call in calls:
            extra = _patched_fields(call) - _HANDLERS[module]
            if extra:
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

    def test_a_super_call_in_an_override_is_not_a_patch_site(self) -> None:
        planted = (
            "class S:\n    def apply_patch(self, p):\n        super().apply_patch(p)\n"
        )

        assert _patch_calls(planted) == []


def _deep() -> object:
    value: object = []
    for _ in range(100):
        value = [value]
    return value


_SCALAR_FIELDS: list[tuple[str, Element, str]] = [
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
        self, kind: str, element: Element, field: str
    ) -> None:
        before = NestingCap().depth(element)  # type: ignore[arg-type]

        with pytest.raises((TypeError, ValueError)):
            element.apply_patch({field: _deep()})

        assert NestingCap().depth(element) == before  # type: ignore[arg-type]
