"""Rollback is complete for an observer that keeps state of its own.

A ``FilteredTableModel`` keeps the unfiltered rows, the filter and the full selection
outside its table. Each of its three mutators changes that state, so each is undone
when the transaction that made the change is refused. The checkpoint that makes it so
is a named message (``will_derive``), not an empty patch, so it neither counts as a
write nor rolls a handler back when the table is installed nowhere; and nothing may
write once the rollback has begun announcing what it restored.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handler_writes import HandlerWrites
from punt_lux.domain.hub.batch_judge import BatchJudge
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.transaction_errors import WriteDuringRollbackError
from punt_lux.domain.programmer_error import ProgrammerError
from punt_lux.protocol.compositions import filtered_table_model
from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.elements import DialogElement, TableElement, TreeElement
from tests.domain.test_nesting_cap_at_the_seam import _DEEP, _OWNER, _SCENE, _nodes

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.hub_display import HubDisplay

_ROWS = [["r1", "idle"], ["r2", "busy"], ["r3", "idle"], ["r4", "busy"]]


def _filtered() -> tuple[HubDisplay, TableElement, TreeElement, FilteredTableModel]:
    table = TableElement(
        id="tb",
        columns=["id", "state"],
        rows=[list(r) for r in _ROWS],
        selection_mode="multi",
        selected_row_ids=frozenset({"r1", "r2"}),
    )
    deep = TreeElement(id="deep")
    store = HubStoreFactory().display
    store.replace_scene(_OWNER, _SCENE, [table, deep])
    model = FilteredTableModel(
        all_rows=tuple(tuple(r) for r in _ROWS),
        key_column=0,
        search_columns=(1,),
        table=table,
    )
    model.on_search("idle")
    return store, table, deep, model


def _state(
    table: TableElement, model: FilteredTableModel
) -> tuple[object, object, object, object]:
    return (
        table.rows,
        table.selected_row_ids,
        model.full_selection,
        model.visible_ids(),
    )


_MUTATORS: list[Callable[[FilteredTableModel], None]] = [
    lambda model: model.on_search("busy"),
    lambda model: model.on_combo(1, "busy"),
    lambda model: model.on_selection_gesture(frozenset({"r3"})),
]


@pytest.mark.parametrize("mutate", _MUTATORS, ids=["search", "combo", "selection"])
def test_a_refused_handler_undoes_each_mutator_of_the_model(
    mutate: Callable[[FilteredTableModel], None],
) -> None:
    store, table, deep, model = _filtered()
    before = _state(table, model)

    def handler() -> None:
        mutate(model)
        deep.apply_patch({"nodes": [_nodes(_DEEP)]})  # refused: past the cap

    refusal = store.write_seam.transaction().run_handler(handler)

    assert refusal is not None
    assert _state(table, model) == before


@pytest.mark.parametrize("mutate", _MUTATORS, ids=["search", "combo", "selection"])
def test_a_mutator_that_stood_changes_the_model(
    mutate: Callable[[FilteredTableModel], None],
) -> None:
    store, table, _, model = _filtered()
    before = _state(table, model)

    refusal = store.write_seam.transaction().run_handler(lambda: mutate(model))

    assert refusal is None
    assert _state(table, model) != before


class TestTheCheckpointIsItsOwnMessage:
    def test_deriving_state_is_not_a_write(self) -> None:
        tree = TreeElement(id="t")
        judge = BatchJudge(lambda _e, _p: None, [])

        judge.note_derivation(tree)

        assert judge.written == ()

    def test_an_empty_patch_is_an_ordinary_write_again(self) -> None:
        tree = TreeElement(id="t")
        judge = BatchJudge(lambda _e, _p: None, [])

        judge.admit(tree, {})

        assert judge.written == (tree,)

    def test_a_derivation_is_still_put_back_on_a_rollback(self) -> None:
        dialog = DialogElement(id="d", title="t")
        judge = BatchJudge(lambda _e, _p: None, [])
        judge.note_derivation(dialog)
        dialog.model.confirm()  # state no patch names

        judge.roll_back()

        assert (dialog.model.confirmed, dialog.visible, dialog.removed) == (
            False,
            True,
            False,
        )

    def test_a_filter_change_on_a_table_no_scene_holds_does_not_roll_back(self) -> None:
        table = TableElement(
            id="loose",
            columns=["id", "state"],
            rows=[list(r) for r in _ROWS],
            selection_mode="multi",
        )
        model = FilteredTableModel(
            all_rows=tuple(tuple(r) for r in _ROWS),
            key_column=0,
            search_columns=(1,),
            table=table,
        )
        store = HubStoreFactory().display

        refusal = store.write_seam.transaction().run_handler(
            lambda: model.on_selection_gesture(frozenset({"r1"}))
        )

        assert refusal is None
        assert model.full_selection == frozenset({"r1"})


class TestNothingWritesWhileARollbackAnnounces:
    def test_a_write_an_observer_makes_then_is_a_programmer_error(self) -> None:
        store = HubStoreFactory().display
        table = TableElement(id="tb", columns=["c"], rows=[["r"]])
        deep = TreeElement(id="deep")
        shallow = TreeElement(id="shallow")
        store.replace_scene(_OWNER, _SCENE, [table, deep, shallow])
        counter = 0

        def bumps_a_counter_on_every_change(_prop: str) -> None:
            nonlocal counter
            counter += 1
            shallow.apply_patch({"label": f"changed {counter} times"})

        table.add_observer(bumps_a_counter_on_every_change)

        def handler() -> None:
            table.apply_patch({"rows": [["s"]]})
            deep.apply_patch({"nodes": [_nodes(_DEEP)]})  # refused: rolls back

        with pytest.raises(WriteDuringRollbackError) as caught:
            store.write_seam.transaction().run_handler(handler)

        assert isinstance(caught.value, ProgrammerError)


class TestOnlyAStatefulObserverIsRegisteredWithItsState:
    def test_add_observer_takes_a_callback_and_nothing_else(self) -> None:
        params = list(inspect.signature(Element.add_observer).parameters)

        assert params == ["self", "observer"]

    def test_the_model_registers_as_a_stateful_observer(self) -> None:
        _, table, _, model = _filtered()
        told: list[str] = []
        original = model.on_change

        def spy(prop: str) -> None:
            told.append(prop)
            original(prop)

        model.on_change = spy  # type: ignore[method-assign]  # watch the telling

        table.apply_patch({"rows": [["r1", "idle"]]})

        assert told[0] == "rows"

    def test_a_stateful_observer_is_not_told_what_a_rollback_restored(self) -> None:
        store, table, deep, model = _filtered()
        told: list[str] = []
        original = model.on_change

        def spy(prop: str) -> None:
            told.append(prop)
            original(prop)

        model.on_change = spy  # type: ignore[method-assign]  # watch the telling

        def handler() -> None:
            model.on_search("busy")
            deep.apply_patch({"nodes": [_nodes(_DEEP)]})  # refused

        store.write_seam.transaction().run_handler(handler)

        # it heard the two properties its own search wrote, and nothing from the restore
        assert told == ["rows", "selected_row_ids"]
        assert table.rows == (("r1", "idle"), ("r3", "idle"))

    def test_the_restore_is_not_public_and_the_state_is_not_exported(self) -> None:
        assert "restore_state" not in dir(FilteredTableModel)
        assert "FilteredTableState" not in filtered_table_model.__all__

    def test_both_classes_are_final(self) -> None:
        assert getattr(FilteredTableModel, "__final__", False) is True
        assert getattr(filtered_table_model.FilteredTableState, "__final__", False)


def test_the_scope_names_its_messages() -> None:
    assert callable(HandlerWrites.will_derive)
    assert callable(HandlerWrites.defer_removal)
