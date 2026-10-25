"""Every write to the store passes the nesting cap at the one seam, by wire depth.

A display's ``inspect_scene`` reply nests the scene's wire form, and a reply the wire
guard refuses retires the dial, so no accepted write may leave an element nested past
the cap. The cap is judged where every element write goes through ``WriteSeam``, by
comparing an element's own wire depth before and after, so it holds for a field that
holds elements (a tree's nodes) and for one that holds arbitrary JSON (a button's
publish payload) alike, and for an install, an ``update`` and a store-level property
write. Each test drives a door and expects the same refusal.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.hub.scene_writer import HubSceneWriter, SceneScope
from punt_lux.domain.hub.write_errors import NestingExceededError
from punt_lux.domain.hub.write_result import WriteAccepted, WriteRejected
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.domain.scope import Scope
from punt_lux.domain.update import AddElement, SetProperty
from punt_lux.operations.models.common import OpError
from punt_lux.operations.scene_installer import SceneInstaller
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.operations.wire_tree import WireTreeDecoder
from punt_lux.protocol.elements import ButtonElement, GroupElement, TreeElement
from punt_lux.protocol.json_payload import MAX_ELEMENT_NESTING

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"
_SCENE = SceneId("s")
_OWNER = Scope.in_process(ConnectionId("local"))
_SEAM_MODULE = "domain/hub/write_seam.py"


def _payload(levels: int) -> dict[str, object]:
    """A JSON object ``levels`` deep: arbitrary data, no element in it."""
    value: dict[str, object] = {"leaf": 1}
    for _ in range(levels):
        value = {"a": value}
    return value


def _nodes(levels: int) -> dict[str, object]:
    node: dict[str, object] = {"label": "leaf"}
    for i in range(levels):
        node = {"label": f"n{i}", "children": [node]}
    return node


def _groups(levels: int) -> GroupElement:
    node = GroupElement(id="g0", children=())
    for i in range(1, levels):
        node = GroupElement(id=f"g{i}", children=(node,))
    return node


def _store_with(*roots: ButtonElement | TreeElement) -> HubDisplay:
    store = HubStoreFactory().display
    store.replace_scene(_OWNER, _SCENE, list(roots))
    return store


def _update(store: HubDisplay, element_id: str, fields: dict[str, object]) -> object:
    return HubSceneWriter(store).apply(
        SceneScope(caller=_OWNER, scene_id=_SCENE),
        [{"id": element_id, "set": fields}],
    )


_DEEP = MAX_ELEMENT_NESTING * 2


class TestAnUpdateOfAFieldThatHoldsNoElement:
    """A button's publish payload is arbitrary JSON, and deepens the wire form."""

    def test_a_deep_publish_payload_is_rejected_with_the_cap_reason(self) -> None:
        store = _store_with(ButtonElement(id="b", label="x"))

        result = _update(
            store, "b", {"publish": {"topic": "t", "payload": _payload(_DEEP)}}
        )

        assert result == WriteRejected(NestingCap.reason())

    def test_a_rejected_publish_leaves_the_button_as_it_was(self) -> None:
        button = ButtonElement(id="b", label="x")
        store = _store_with(button)

        _update(store, "b", {"publish": {"topic": "t", "payload": _payload(_DEEP)}})

        assert button.to_dict().get("publish") is None

    def test_a_shallow_publish_payload_is_accepted(self) -> None:
        store = _store_with(ButtonElement(id="b", label="x"))

        result = _update(
            store, "b", {"publish": {"topic": "t", "payload": _payload(3)}}
        )

        assert isinstance(result, WriteAccepted)


class TestAStoreLevelPropertyWrite:
    """``HubDisplay.apply(SetProperty)`` is a write like any other."""

    def test_a_deep_tree_is_refused(self) -> None:
        store = _store_with(TreeElement(id="t"))

        with pytest.raises(NestingExceededError) as raised:
            store.apply(
                _OWNER,
                SetProperty(
                    scene_id=_SCENE,
                    element_id=ElementId("t"),
                    field="nodes",
                    value=[_nodes(_DEEP)],
                ),
            )

        assert raised.value.reason == NestingCap.reason()

    def test_a_deep_publish_payload_is_refused(self) -> None:
        store = _store_with(ButtonElement(id="b", label="x"))

        with pytest.raises(NestingExceededError):
            store.apply(
                _OWNER,
                SetProperty(
                    scene_id=_SCENE,
                    element_id=ElementId("b"),
                    field="publish",
                    value={"topic": "t", "payload": _payload(_DEEP)},
                ),
            )

    def test_a_refused_write_changes_nothing(self) -> None:
        tree = TreeElement(id="t")
        store = _store_with(tree)

        with pytest.raises(NestingExceededError):
            store.apply(
                _OWNER,
                SetProperty(
                    scene_id=_SCENE,
                    element_id=ElementId("t"),
                    field="nodes",
                    value=[_nodes(_DEEP)],
                ),
            )

        assert tree.nodes == ()

    def test_a_shallow_write_is_applied(self) -> None:
        tree = TreeElement(id="t")
        store = _store_with(tree)

        store.apply(
            _OWNER,
            SetProperty(
                scene_id=_SCENE,
                element_id=ElementId("t"),
                field="nodes",
                value=[_nodes(2)],
            ),
        )

        assert tree.nodes != ()


class TestAnInstall:
    def test_a_scene_replace_with_a_too_deep_root_is_refused(self) -> None:
        store = _store_with(ButtonElement(id="b", label="x"))

        with pytest.raises(NestingExceededError):
            store.replace_scene(_OWNER, _SCENE, [_groups(_DEEP)])

    def test_a_refused_replace_keeps_the_scene_it_would_have_replaced(self) -> None:
        store = _store_with(ButtonElement(id="b", label="x"))

        with pytest.raises(NestingExceededError):
            store.replace_scene(_OWNER, _SCENE, [_groups(_DEEP)])

        assert [e.id for e in store.scene_roots(_SCENE)] == ["b"]

    def test_an_add_element_that_is_too_deep_is_refused(self) -> None:
        store = HubStoreFactory().display

        with pytest.raises(NestingExceededError):
            store.apply(
                _OWNER,
                AddElement(scene_id=_SCENE, element=_groups(_DEEP), parent_id=None),
            )


class _Marks:
    """Records what the install marked for the replicator."""

    def __init__(self) -> None:
        self.dirtied: list[SceneId] = []

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.dirtied.append(scene_id)

    def mark_menus(self) -> None:
        """Unused: an install never marks the menu bar."""


class TestTheInstallDoorTellsTheAgentWhy:
    def test_a_too_deep_submission_is_rejected_with_the_cap_reason(self) -> None:
        store = _store_with(ButtonElement(id="b", label="x"))
        marks = _Marks()
        submission = SceneSubmission.of(
            [_groups(_DEEP)], "s", ScenePresentation(frame_id="s"), None
        )

        result = SceneInstaller(store, marks).install(submission, owner=_OWNER)

        assert result == OpError(code="rejected", reason=NestingCap.reason())

    def test_a_rejected_submission_marks_nothing_and_keeps_the_scene(self) -> None:
        store = _store_with(ButtonElement(id="b", label="x"))
        marks = _Marks()
        submission = SceneSubmission.of(
            [_groups(_DEEP)], "s", ScenePresentation(frame_id="s"), None
        )

        SceneInstaller(store, marks).install(submission, owner=_OWNER)

        assert marks.dirtied == []
        assert [e.id for e in store.scene_roots(_SCENE)] == ["b"]


class TestATreeTooDeepToDecodeOrPatch:
    """A form deeper than the interpreter can walk is the cap's refusal, not a fault."""

    _RECURSION = 3000

    def test_an_update_to_it_is_rejected_with_the_cap_reason(self) -> None:
        store = _store_with(TreeElement(id="t"))

        result = _update(store, "t", {"nodes": [_nodes(self._RECURSION)]})

        assert result == WriteRejected(NestingCap.reason())

    def test_a_store_level_write_of_it_is_refused_with_the_cap_reason(self) -> None:
        store = _store_with(TreeElement(id="t"))

        with pytest.raises(NestingExceededError):
            store.apply(
                _OWNER,
                SetProperty(
                    scene_id=_SCENE,
                    element_id=ElementId("t"),
                    field="nodes",
                    value=[_nodes(self._RECURSION)],
                ),
            )

    def test_a_show_of_it_is_rejected_at_decode_with_the_cap_reason(self) -> None:
        from punt_lux.domain.hub.hub_factory import hub_element_factory

        wire: dict[str, object] = {
            "kind": "tree",
            "id": "t",
            "nodes": [_nodes(self._RECURSION)],
        }

        decoded = WireTreeDecoder(hub_element_factory).decode([wire], ConnectionId("c"))

        assert decoded == OpError(code="rejected", reason=NestingCap.reason())


def _constructions_of(name: str) -> set[str]:
    """The modules (relative to the package) that build a ``name`` instance."""
    return {
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if _builds(path.read_text(encoding="utf-8"), name)
    }


def _builds(source: str, name: str) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == name
        for call in ast.walk(ast.parse(source))
    )


class TestTheCapIsAskedAtTheSeamAlone:
    def test_the_cap_is_built_in_the_seam_and_nowhere_else(self) -> None:
        assert _constructions_of("NestingCap") == {_SEAM_MODULE}

    def test_a_planted_second_asker_is_found(self) -> None:
        assert _builds(
            "def f(roots):\n    return NestingCap().refusal(roots)\n", "NestingCap"
        )

    def test_the_cap_has_no_per_kind_declaration_left(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8") for path in _SRC.rglob("*.py")
        )

        assert "NESTING_FIELDS" not in text
        assert "patches_nested_content" not in text
