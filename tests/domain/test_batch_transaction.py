"""An agent's batch is one transaction: all its effects stand, or none do.

An observer woken by a write may write other elements, and the judge may refuse one
of those writes. Then the agent's whole batch rolls back, the elements the observers
wrote included, the observers hear the restored values, and the agent is told why.
After the commit the final state of every element written is measured against the
nesting cap once more.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.scene_writer import HubSceneWriter, SceneScope
from punt_lux.domain.hub.write_refusals import NestingExceededError, UnheldTargetError
from punt_lux.domain.hub.write_result import WriteAccepted, WriteRejected
from punt_lux.domain.hub.write_seam import WriteSeam
from punt_lux.domain.ids import ElementId
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.protocol.elements import TableElement, TreeElement
from tests.domain.test_nesting_cap_at_the_seam import _DEEP, _OWNER, _SCENE, _nodes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.hub.hub_display import HubDisplay

_SHALLOW = 2


def _rows(value: str) -> list[dict[str, object]]:
    return [{"id": "tb", "set": {"rows": [[value]]}}]


def _apply(store: HubDisplay, patches: list[dict[str, object]]) -> object:
    return HubSceneWriter(store).apply(
        SceneScope(caller=_OWNER, scene_id=_SCENE), patches
    )


def _scene() -> tuple[HubDisplay, TableElement, TreeElement, TreeElement]:
    """A table and two trees an observer of the table may write."""
    table = TableElement(id="tb", columns=["c"], rows=[["r"]])
    shallow, deep = TreeElement(id="shallow"), TreeElement(id="deep")
    store = HubStoreFactory().display
    store.replace_scene(_OWNER, _SCENE, [table, shallow, deep])
    return store, table, shallow, deep


def _writes(table: TableElement, tree: TreeElement, levels: int) -> object:
    """An observer of ``table`` that derives ``tree`` from the rows it now holds."""

    def on_change(prop: str) -> None:
        if prop == "rows" and table.rows == (("s",),) and tree.nodes == ():
            tree.apply_patch({"nodes": [_nodes(levels)]})

    return on_change


class TestARefusedObserverWriteRollsTheBatchBack:
    def test_the_agent_is_told_why_and_its_own_write_is_undone(self) -> None:
        store, table, _, deep = _scene()
        table.add_observer(_writes(table, deep, _DEEP))  # type: ignore[arg-type]

        result = _apply(store, _rows("s"))

        assert result == WriteRejected(NestingCap.reason())
        assert table.rows == (("r",),)

    def test_an_observer_write_made_before_the_refusal_is_undone_too(self) -> None:
        store, table, shallow, deep = _scene()
        table.add_observer(_writes(table, shallow, _SHALLOW))  # type: ignore[arg-type]
        table.add_observer(_writes(table, deep, _DEEP))  # type: ignore[arg-type]

        result = _apply(store, _rows("s"))

        assert isinstance(result, WriteRejected)
        assert (shallow.nodes, deep.nodes, table.rows) == ((), (), (("r",),))

    def test_the_observers_of_a_restored_element_hear_the_restored_values(self) -> None:
        store, table, shallow, deep = _scene()
        table.add_observer(_writes(table, shallow, _SHALLOW))  # type: ignore[arg-type]
        table.add_observer(_writes(table, deep, _DEEP))  # type: ignore[arg-type]
        heard: list[str] = []
        shallow.add_observer(heard.append)
        seen_at_restore: list[int] = []
        shallow.add_observer(lambda _prop: seen_at_restore.append(len(shallow.nodes)))

        _apply(store, _rows("s"))

        assert heard == ["nodes", "nodes"]  # the write, then the restoration
        assert seen_at_restore == [1, 0]  # the second hearing sees the restored tree

    def test_a_batch_no_observer_refuses_still_lands(self) -> None:
        store, table, shallow, _ = _scene()
        table.add_observer(_writes(table, shallow, _SHALLOW))  # type: ignore[arg-type]

        result = _apply(store, _rows("s"))

        assert (result, table.rows, shallow.nodes != ()) == (
            WriteAccepted(),
            (("s",),),
            True,
        )


class TestAnObserverThatFailsForAnotherReason:
    def test_it_is_logged_for_what_it_was_and_the_batch_lands(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        store, table, _, _ = _scene()
        survivor: list[str] = []

        def broken(prop: str) -> None:
            msg = "the observer's own bug"
            raise RuntimeError(msg)

        table.add_observer(broken)
        table.add_observer(survivor.append)

        with caplog.at_level(logging.ERROR):
            result = _apply(store, _rows("s"))

        assert (result, table.rows, survivor) == (
            WriteAccepted(),
            (("s",),),
            ["rows"],
        )
        assert "RuntimeError" in caplog.text
        assert "rows" in caplog.text


class TestTheFinalStateIsMeasuredAgainTheCap:
    def test_a_breach_the_judge_missed_rolls_the_batch_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A judge that approves everything: the combination it failed to measure.

        def approve(
            _self: WriteSeam, _element: Element, _patch: Mapping[str, object]
        ) -> None:
            return None

        monkeypatch.setattr(WriteSeam, "admit", approve)
        store, table, _, deep = _scene()
        table.add_observer(_writes(table, deep, _DEEP))  # type: ignore[arg-type]

        result = _apply(store, _rows("s"))

        assert result == WriteRejected(NestingCap.reason())
        assert (deep.nodes, table.rows) == ((), (("r",),))


class TestAStoreLevelWriteRaisesTheRefusalItself:
    def test_a_nesting_refusal_by_an_observer_is_a_nesting_error(self) -> None:
        store, table, _, deep = _scene()
        table.add_observer(_writes(table, deep, _DEEP))  # type: ignore[arg-type]

        with pytest.raises(NestingExceededError):
            store.write_seam.set_property(_SCENE, ElementId("tb"), "rows", [["s"]])

        assert (deep.nodes, table.rows) == ((), (("r",),))

    def test_an_unheld_target_refusal_by_an_observer_is_an_unheld_target_error(
        self,
    ) -> None:
        store, table, _, _ = _scene()
        loose = TreeElement(id="loose")  # installed in no scene the Hub holds

        def writes_the_loose_tree(prop: str) -> None:
            if prop == "rows" and table.rows == (("s",),):
                loose.apply_patch({"label": "x"})

        table.add_observer(writes_the_loose_tree)

        with pytest.raises(UnheldTargetError) as raised:
            store.write_seam.set_property(_SCENE, ElementId("tb"), "rows", [["s"]])

        assert not isinstance(raised.value, NestingExceededError)
        assert (loose.label, table.rows) == ("", (("r",),))
