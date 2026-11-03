"""A rolled-back batch leaves observer-derived state as it was, not as a new dataset.

A ``FilteredTableModel`` keeps the unfiltered rows, the filter and the full selection
outside the table element. A rollback that restored the element alone would let the
model adopt the restored (filtered) rows as its whole dataset and lose every hidden
row and hidden selection. The restore is a restore of the model's state, whatever the
order the properties were written in.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.batch_judge import BatchJudge
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.scene_writer import HubSceneWriter, SceneScope
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.elements import TableElement, TreeElement
from tests.domain.test_nesting_cap_at_the_seam import _DEEP, _OWNER, _SCENE, _nodes

if TYPE_CHECKING:
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

    def refuse_when_rows_change(prop: str) -> None:
        if prop == "rows" and table.rows == (("n1", "idle"),):
            deep.apply_patch({"nodes": [_nodes(_DEEP)]})

    table.add_observer(refuse_when_rows_change)
    return store, table, deep, model


def _batch_that_is_refused(store: HubDisplay) -> object:
    patches: list[dict[str, object]] = [{"id": "tb", "set": {"rows": [["n1", "idle"]]}}]
    return HubSceneWriter(store).apply(
        SceneScope(caller=_OWNER, scene_id=_SCENE), patches
    )


def test_a_rolled_back_batch_restores_the_models_dataset_and_selection() -> None:
    store, table, _, model = _filtered()
    before = (table.rows, table.selected_row_ids, model.full_selection)

    result = _batch_that_is_refused(store)

    assert isinstance(result, WriteRejected)
    assert (table.rows, table.selected_row_ids, model.full_selection) == before
    clear = model.visible_ids()
    model.on_search("")
    assert (clear, model.visible_ids()) == (
        frozenset({"r1", "r3"}),
        frozenset({"r1", "r2", "r3", "r4"}),
    )
    assert model.full_selection == frozenset({"r1", "r2"})


def test_stateless_observers_hear_the_restore_in_the_order_it_was_written() -> None:
    _, table, _, _ = _filtered()
    heard: list[str] = []
    table.add_observer(heard.append)
    names = [f"prop_{n}" for n in range(12)]
    judge = BatchJudge(lambda _element, _patch: None, [])

    judge.admit(table, dict.fromkeys(names))
    judge.roll_back()

    assert heard == names


@pytest.mark.parametrize("seed", ["0", "1", "2", "3", "7", "42"])
def test_the_restore_does_not_depend_on_the_hash_seed(seed: str) -> None:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            str(Path(__file__)),
            "-k",
            "not hash_seed",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
