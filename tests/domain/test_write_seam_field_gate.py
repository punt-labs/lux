"""The field gate refuses every child-bearing field on both write paths.

A structural field carries child Elements, so replacing its value would install a
new child set and evict the old one — work only ``show`` performs. Two seams must
refuse it: the batch ``update`` path (:class:`HubSceneWriter`) and the D21 store
primitive (:meth:`WriteSeam.set_property`). The legacy child-bearing fields are
exactly ``{children, pages, tabs}``; ``tabs`` is the third, easy to miss because
``LegacyTabBarElement`` names its children neither ``children`` nor ``pages``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from typing import cast

import pytest

from punt_lux.domain.element import Element
from punt_lux.domain.hub.deferral_errors import StructuralFieldWriteError
from punt_lux.domain.hub.field_gate import FieldGate
from punt_lux.domain.hub.hub_display import HubDisplay, UnknownElementError
from punt_lux.domain.hub.scene_writer import HubSceneWriter
from punt_lux.domain.hub.write_errors import ImmutableFieldError
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.protocol.elements import Tab, TabBarElement
from punt_lux.protocol.elements.layout import LegacyTabBarElement

_SCENE = SceneId("gate-scene")
_CONN = ConnectionId("gate-conn")
_TAB_BAR_ID = ElementId("tb")

# Pinning a child to this seed disables hash randomization, and under it the
# pre-fix ``next(iter(SET & keys))`` names the wrong field. The fixed-precedence
# gate must still name the right one, so a reintroduced set-iteration is caught
# deterministically rather than on only the seeds where the order happens to flip.
_ADVERSARIAL_HASHSEED = "0"


def _assert_gate_names_field_under_adversarial_seed(
    *, set_name: str, error_module: str, error_name: str, keys: str, expected: str
) -> None:
    """Run the gate in a child pinned to a seed the pre-fix bug fails under.

    The child first asserts the seed is adversarial — the naive set-iteration names
    something other than ``expected`` — so if a future interpreter changes that
    order the guard fails loud instead of passing vacuously. It then asserts the
    gate names ``expected``, which a reintroduced ``next(iter(...))`` would not.
    """
    script = textwrap.dedent(f"""
        from punt_lux.domain.hub.field_gate import FieldGate, {set_name} as _set
        from {error_module} import {error_name}
        from punt_lux.domain.ids import ElementId

        keys = {keys}
        assert next(iter(_set & keys.keys())) != {expected!r}
        try:
            FieldGate.reject(ElementId("x"), keys)
        except {error_name} as exc:
            assert exc.field == {expected!r}, exc.field
        else:
            raise AssertionError("gate did not reject")
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=os.environ | {"PYTHONHASHSEED": _ADVERSARIAL_HASHSEED},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _seed_legacy_tab_bar() -> HubDisplay:
    """Install a ``LegacyTabBarElement`` root whose tab holds a legacy child."""
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    bar = LegacyTabBarElement(
        id=str(_TAB_BAR_ID),
        tabs=[
            {
                "label": "One",
                "children": [{"id": "old-child", "kind": "slider", "label": "s"}],
            }
        ],
    )
    # The production scene decoder yields legacy elements as ``Element``; the cast
    # mirrors that runtime contract past a codec-signature variance quibble.
    hub_display.apply(
        _CONN,
        AddElement(scene_id=_SCENE, element=cast("Element", bar), parent_id=None),
    )
    return hub_display


def test_update_set_tabs_on_legacy_tab_bar_is_rejected() -> None:
    """A ``set`` of ``tabs`` on a legacy tab_bar root defers to ``show``.

    Without ``tabs`` in the structural set the write would slip past the gate and
    ``dataclasses.replace`` the root's tab list, rebinding only the root — the new
    tab children never installed, the old never evicted. The gate refuses it whole,
    leaving the stored root's tabs untouched.
    """
    hub_display = _seed_legacy_tab_bar()
    writer = HubSceneWriter(hub_display)

    result = writer.apply(
        _CONN,
        _SCENE,
        [
            {
                "id": str(_TAB_BAR_ID),
                "set": {
                    "tabs": [
                        {
                            "label": "New",
                            "children": [{"id": "new-child", "kind": "text"}],
                        }
                    ]
                },
            }
        ],
    )

    assert isinstance(result, WriteRejected)
    assert "tabs" in result.reason
    assert "show" in result.reason

    stored = cast("LegacyTabBarElement", hub_display.resolve(_SCENE, _TAB_BAR_ID))
    assert stored.tabs[0]["label"] == "One"
    with pytest.raises(UnknownElementError):
        hub_display.resolve(_SCENE, ElementId("new-child"))


def test_set_property_structural_field_is_rejected_fail_loud() -> None:
    """The D21 store primitive refuses a structural field before touching storage.

    ``set_property`` is safe today only because no migrated element exposes a
    ``_set_tabs`` setter. The gate makes that safety explicit: a structural field
    can never reach the store primitive, so a later composite gaining a setter
    cannot reopen the desync.
    """
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    bar = TabBarElement(
        id=str(_TAB_BAR_ID),
        tabs=(Tab(tab_id="tab-1", label="One", children=()),),
        active_tab="tab-1",
    )
    hub_display.apply(_CONN, AddElement(scene_id=_SCENE, element=bar, parent_id=None))

    with pytest.raises(StructuralFieldWriteError):
        hub_display.write_seam.set_property(_SCENE, _TAB_BAR_ID, "tabs", [])


def test_reject_names_highest_precedence_immutable_field() -> None:
    """With ``id`` and ``kind`` both present, the gate always names ``id``.

    Set-intersection yielded whichever field the set happened to iterate first,
    so the reason varied across runs. A fixed precedence makes it deterministic.
    The child pinned to an adversarial hash seed turns the contract into a
    guaranteed regression guard against a reintroduced ``next(iter(...))``.
    """
    with pytest.raises(ImmutableFieldError) as caught:
        FieldGate.reject(ElementId("x"), {"kind": "text", "id": "new"})
    assert caught.value.field == "id"

    _assert_gate_names_field_under_adversarial_seed(
        set_name="_IMMUTABLE_FIELDS",
        error_module="punt_lux.domain.hub.write_errors",
        error_name="ImmutableFieldError",
        keys='{"kind": "text", "id": "new"}',
        expected="id",
    )


def test_reject_names_highest_precedence_structural_field() -> None:
    """With every structural field present, the gate always names ``children``.

    The adversarial-seed child makes the fixed precedence a guaranteed guard: a
    reintroduced set-iteration would name ``tabs`` under that seed, not ``children``.
    """
    fields: dict[str, object] = {"tabs": [], "pages": [], "children": []}
    with pytest.raises(StructuralFieldWriteError) as caught:
        FieldGate.reject(ElementId("x"), fields)
    assert caught.value.field == "children"

    _assert_gate_names_field_under_adversarial_seed(
        set_name="_STRUCTURAL_FIELDS",
        error_module="punt_lux.domain.hub.deferral_errors",
        error_name="StructuralFieldWriteError",
        keys='{"tabs": [], "pages": [], "children": []}',
        expected="children",
    )


def test_set_property_non_structural_field_still_applies() -> None:
    """The gate blocks only structural fields — a scalar set still commits."""
    hub_display = HubDisplay()
    hub_display.register_client(_CONN)
    bar = TabBarElement(
        id=str(_TAB_BAR_ID),
        tabs=(
            Tab(tab_id="tab-1", label="One", children=()),
            Tab(tab_id="tab-2", label="Two", children=()),
        ),
        active_tab="tab-1",
    )
    hub_display.apply(_CONN, AddElement(scene_id=_SCENE, element=bar, parent_id=None))

    hub_display.write_seam.set_property(_SCENE, _TAB_BAR_ID, "active_tab", "tab-2")

    stored = hub_display.resolve(_SCENE, _TAB_BAR_ID)
    assert isinstance(stored, TabBarElement)
    assert stored.active_tab == "tab-2"
