"""An element write is judged in the scene that owns the element written.

A handler that fires in scene A may patch an element of scene B, or one the Hub holds
in no scene, and an agent's write may wake an observer that patches some other
element. The seam judges each of those writes against the scene its target lives in,
and refuses a target no scene holds, so the nesting cap holds whoever writes and
wherever the target sits.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.batch_judge import BatchJudge
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.scene_writer import HubSceneWriter, SceneScope
from punt_lux.domain.hub.write_errors import NestingExceededError
from punt_lux.domain.hub.write_result import WriteAccepted, WriteRejected
from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.protocol.elements import ButtonElement, TableElement, TreeElement
from tests.domain.test_handler_writes_are_judged import _fire
from tests.domain.test_nesting_cap_at_the_seam import (
    _DEEP,
    _OWNER,
    _SCENE,
    _nodes,
    _store_with,
    _update,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.hub.hub_display import HubDisplay

_OTHER = SceneId("other")


def _writes_nodes(tree: TreeElement, levels: int) -> Callable[[object], None]:
    """A handler that patches ``tree`` with ``levels`` levels of nodes."""

    def write(_event: object) -> None:
        tree.apply_patch({"nodes": [_nodes(levels)]})

    return write


def _button_that_writes(handler: Callable[[ButtonClicked], None]) -> ButtonElement:
    button = ButtonElement(id="b", label="x")
    button.add_handler(ButtonClicked, handler)
    return button


def _two_scenes(button: ButtonElement, other: TreeElement) -> HubDisplay:
    store = HubStoreFactory().display
    store.replace_scene(_OWNER, _SCENE, [button])
    store.replace_scene(_OWNER, _OTHER, [other])
    return store


class TestAHandlerWritesAnElementOfAnotherScene:
    def test_a_write_past_the_cap_into_another_scene_is_refused(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        tree = TreeElement(id="t")
        button = _button_that_writes(_writes_nodes(tree, _DEEP))
        store = _two_scenes(button, tree)

        with caplog.at_level(logging.ERROR):
            _fire(store, button)

        assert tree.nodes == ()

    def test_a_shallow_write_into_another_scene_is_applied(self) -> None:
        tree = TreeElement(id="t")
        button = _button_that_writes(_writes_nodes(tree, 2))
        store = _two_scenes(button, tree)

        _fire(store, button)

        assert tree.nodes != ()

    def test_a_same_named_element_of_the_firing_scene_is_not_the_target(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The target is found by identity, so a namesake is never measured for it."""
        namesake = TreeElement(id="t")
        target = TreeElement(id="t")
        button = _button_that_writes(_writes_nodes(target, _DEEP))
        store = HubStoreFactory().display
        store.replace_scene(_OWNER, _SCENE, [button, namesake])
        store.replace_scene(_OWNER, _OTHER, [target])

        with caplog.at_level(logging.ERROR):
            _fire(store, button)

        assert target.nodes == ()


class TestAHandlerWritesAnElementNoSceneHolds:
    def test_the_write_is_refused(self, caplog: pytest.LogCaptureFixture) -> None:
        tree = TreeElement(id="loose")

        def relabel(_event: object) -> None:
            tree.apply_patch({"label": "x"})

        button = _button_that_writes(relabel)
        store = _store_with(button)

        with caplog.at_level(logging.ERROR):
            _fire(store, button)

        assert tree.label == ""
        assert "installed in no scene" in caplog.text


def _table_with_a_deepening_observer(levels: int) -> tuple[TableElement, TreeElement]:
    """A table whose ``rows`` write wakes an observer that patches a tree."""
    tree = TreeElement(id="t")
    table = TableElement(id="tb", columns=["c"], rows=[["r"]])
    deepen = _writes_nodes(tree, levels)

    def on_change(prop: str) -> None:
        if prop == "rows":
            deepen(prop)

    table.add_observer(on_change)
    return table, tree


def _store_of(table: TableElement, tree: TreeElement) -> HubDisplay:
    store = HubStoreFactory().display
    store.replace_scene(_OWNER, _SCENE, [table, tree])
    return store


class TestAnObserverWokenByAnAgentWrite:
    def test_a_write_it_makes_past_the_cap_is_refused(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        table, tree = _table_with_a_deepening_observer(_DEEP)
        store = _store_of(table, tree)

        with caplog.at_level(logging.ERROR):
            _update(store, "tb", {"rows": [["s"]]})

        assert tree.nodes == ()

    def test_a_refused_write_rolls_the_agents_own_write_back_and_says_why(
        self,
    ) -> None:
        table, tree = _table_with_a_deepening_observer(_DEEP)
        store = _store_of(table, tree)

        result = _update(store, "tb", {"rows": [["s"]]})

        assert result == WriteRejected(NestingCap.reason())
        assert table.rows == (("r",),)

    def test_a_shallow_write_it_makes_is_applied(self) -> None:
        table, tree = _table_with_a_deepening_observer(2)
        store = _store_of(table, tree)

        _update(store, "tb", {"rows": [["s"]]})

        assert tree.nodes != ()

    def test_a_store_level_property_write_judges_the_observer_too(self) -> None:
        table, tree = _table_with_a_deepening_observer(_DEEP)
        store = _store_of(table, tree)

        with pytest.raises(NestingExceededError):
            store.write_seam.set_property(_SCENE, ElementId("tb"), "rows", [["s"]])

        assert (tree.nodes, table.rows) == ((), (("r",),))


class TestABatchJudge:
    """The batch was judged whole, so each pre-judged write is let through, once."""

    def test_the_pre_judged_write_is_not_judged_again(self) -> None:
        seen: list[Element] = []
        target = TreeElement(id="t")
        fields: Mapping[str, object] = {"label": "x"}
        judge = BatchJudge(
            lambda element, _patch: seen.append(element), [(target, fields)]
        )

        judge(target, fields)

        assert seen == []

    def test_a_second_write_of_the_same_patch_is_judged(self) -> None:
        seen: list[Element] = []
        target = TreeElement(id="t")
        fields: Mapping[str, object] = {"label": "x"}
        judge = BatchJudge(
            lambda element, _patch: seen.append(element), [(target, fields)]
        )

        judge(target, fields)
        judge(target, fields)

        assert seen == [target]

    def test_another_patch_to_the_target_is_judged(self) -> None:
        """An observer's write to a batch target is not the batch's own write."""
        seen: list[Element] = []
        target = TreeElement(id="t")
        judge = BatchJudge(
            lambda element, _patch: seen.append(element), [(target, {"label": "x"})]
        )

        judge(target, {"label": "x"})  # equal, but not the same mapping

        assert seen == [target]

    def test_a_write_to_an_element_outside_the_batch_is_judged(self) -> None:
        seen: list[Element] = []
        target = TreeElement(id="t")
        other = TreeElement(id="o")
        fields: Mapping[str, object] = {"label": "x"}
        judge = BatchJudge(
            lambda element, _patch: seen.append(element), [(target, fields)]
        )

        judge(other, fields)

        assert seen == [other]


def _batch(first: str, second: str) -> list[dict[str, object]]:
    rows: dict[str, object] = {"id": "tb", "set": {"rows": [["s"]]}}
    label: dict[str, object] = {"id": "t", "set": {"label": "L"}}
    return [rows, label] if first == "tb" else [label, rows]


class TestABatchWhoseObserverWritesAnotherTarget:
    """An observer's write to a later target is judged, whatever the batch's order."""

    @pytest.mark.parametrize("first", ["tb", "t"])
    def test_the_deep_write_leaves_no_deep_tree(self, first: str) -> None:
        table, tree = _table_with_a_deepening_observer(_DEEP)
        store = _store_of(table, tree)

        HubSceneWriter(store).apply(
            SceneScope(caller=_OWNER, scene_id=_SCENE),
            _batch(first, "t" if first == "tb" else "tb"),
        )

        assert tree.nodes == ()

    @pytest.mark.parametrize("first", ["tb", "t"])
    def test_a_refused_observer_write_rejects_the_whole_batch(self, first: str) -> None:
        table, tree = _table_with_a_deepening_observer(_DEEP)
        store = _store_of(table, tree)

        result = HubSceneWriter(store).apply(
            SceneScope(caller=_OWNER, scene_id=_SCENE),
            _batch(first, "t" if first == "tb" else "tb"),
        )

        assert (result, table.rows, tree.label) == (
            WriteRejected(NestingCap.reason()),
            (("r",),),
            "",
        )

    def test_a_shallow_observer_write_lets_the_batch_through(self) -> None:
        table, tree = _table_with_a_deepening_observer(2)
        store = _store_of(table, tree)

        result = HubSceneWriter(store).apply(
            SceneScope(caller=_OWNER, scene_id=_SCENE), _batch("tb", "t")
        )

        assert (isinstance(result, WriteAccepted), tree.label) == (True, "L")
