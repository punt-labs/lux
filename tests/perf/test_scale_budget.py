"""Scale-perf guardrail for the lux-qfzu epic — 1000 elements, 10k table rows.

``test_frame_budget.py`` proved the pattern at 10 ``TextElement`` instances;
this module extends it to the two scales the epic's four fix beads (texture
eviction, filter memoization, selection scan, stack-layout skip) compare
against. Same discipline: pure-Python dispatch cost via ``RecordingRenderer``,
absolute wall-clock bounds loose enough to survive CI noise (~70x above
measured cost, per the sibling module's rationale), immune to GPU/GL timing
because nothing here touches ImGui.

Two classes of cost are measured, matching what is actually reachable without
a live display:

- The **outer render walk** — ``Element.render()`` dispatch over a scene, the
  same seam ``RenderLoop._render_framed_scene`` (render_loop.py:1043-1060)
  exercises per frame for every element in a scene.
- The **Hub-side table model cost** — ``FilteredTableModel``'s per-event
  filter scan and ``TableElement``'s per-patch selection-intersect scan. Both
  are O(rows) Python work with no ImGui dependency: the actual row *painting*
  (``TableRowPainter``, the list-clipper walk) requires a live ImGui frame
  and cannot run in-process, but the Hub-side scans these two fix beads
  target (#3 filter memoization, #4 selection O(rows)->O(selected)) run on
  every filter keystroke and every selection patch, live or not.

Marked ``slow`` (not the mission-requested ``perf``): ``pyproject.toml``
already wires ``slow`` into ``addopts`` and ``make test-slow``, and the
module's write-set here does not extend to ``pyproject.toml``. An
unregistered ``perf`` marker would not be excluded from the default
``make test`` gate, defeating the point of the guardrail.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, Self

import pytest

from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.compositions.table_composition import TableComposition
from punt_lux.protocol.compositions.table_composition_spec import (
    TableCompositionSpec,
)
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderers import RecordingLog, RecordingRendererFactory

# -- scene scale --------------------------------------------------------

_SCENE_ELEMENT_COUNT: Final[int] = 1000
_SCENE_FRAMES: Final[int] = 20
# The sibling test_ten_text_elements budget is 20 ms / 10 elements == 2 ms
# per element (a ~70x margin over its own ~0.28 ms measured cost); this
# scales that per-element budget linearly to 1000 elements. Measured
# locally at ~165 ms/frame, so the ~12x headroom left here still catches an
# O(n^2) blow-up or an accidental per-element I/O call without flaking
# under CI load.
_SCENE_BUDGET_SECONDS: Final[float] = 2.000

# -- table scale ----------------------------------------------------------

_TABLE_ROW_COUNT: Final[int] = 10_000
_TABLE_FILTERED_ROW_COUNT: Final[int] = 100
_TABLE_SELECTION_COUNT: Final[int] = 100
_TABLE_ITERATIONS: Final[int] = 20
# Hub-side O(rows) scans over 10k rows, pure Python (set/tuple work, no
# I/O, no ImGui). Loose absolute bound for the same load-independence
# reasons as the scene budget above.
_TABLE_BUDGET_SECONDS: Final[float] = 0.500


def _emit(_msg: object) -> None:
    """No-op emit channel for elements built outside the Hub's real bus."""


class MixedSceneBuilder:
    """Build a ~1000-element scene mixing text, button, and checkbox kinds.

    The three kinds cycle round-robin so the scene exercises every leaf-kind
    dispatch branch the render walk takes, not just one repeated kind.
    """

    _factory: RecordingRendererFactory
    _count: int
    __slots__ = ("_count", "_factory")

    def __new__(cls, factory: RecordingRendererFactory, *, count: int) -> Self:
        self = super().__new__(cls)
        self._factory = factory
        self._count = count
        return self

    def build(self) -> tuple[TextElement | ButtonElement | CheckboxElement, ...]:
        """Return ``count`` elements cycling text, button, checkbox kinds."""
        elements: list[TextElement | ButtonElement | CheckboxElement] = []
        for i in range(self._count):
            kind = i % 3
            if kind == 0:
                elements.append(
                    TextElement(
                        renderer_factory=self._factory,
                        emit=_emit,
                        id=f"text-{i}",
                        content=f"row-{i}",
                    )
                )
            elif kind == 1:
                elements.append(
                    ButtonElement(
                        renderer_factory=self._factory,
                        emit=_emit,
                        id=f"button-{i}",
                        label=f"go-{i}",
                    )
                )
            else:
                elements.append(
                    CheckboxElement(
                        renderer_factory=self._factory,
                        emit=_emit,
                        id=f"checkbox-{i}",
                        label=f"toggle-{i}",
                        value=i % 2 == 0,
                    )
                )
        return tuple(elements)


class TableScaleFixture:
    """Build the three ``show_table`` wire-shape scenarios lux-qfzu.1 covers.

    Each scenario builds a fresh composition via ``TableComposition.build``
    — the real production entry point (``operations/conveniences.py`` and
    ``apps.beads`` both call it) — so the measured cost is the same
    ``FilteredTableModel`` / ``TableElement`` path a live show_table call
    exercises, not a hand-rolled stand-in.
    """

    __slots__ = ()

    @staticmethod
    def _rows(row_count: int) -> tuple[tuple[object, ...], ...]:
        """Return ``row_count`` rows of (id, name, status)."""
        return tuple(
            (f"row-{i}", f"item-{i}", "active" if i % 100 == 0 else "idle")
            for i in range(row_count)
        )

    @classmethod
    def _spec(cls, *, row_count: int, with_search_filter: bool) -> TableCompositionSpec:
        filters: tuple[dict[str, object], ...] = (
            ({"type": "search", "column": [2]},) if with_search_filter else ()
        )
        return TableCompositionSpec(
            columns=("id", "name", "status"),
            rows=cls._rows(row_count),
            filters=filters,
            key_column=0,
            table_id="scale-table",
        )

    @classmethod
    def build_unfiltered(
        cls, row_count: int
    ) -> tuple[TableElement, FilteredTableModel]:
        """Build a table + model with chrome but no filter applied yet."""
        spec = cls._spec(row_count=row_count, with_search_filter=True)
        roots = TableComposition.build(spec)
        table = cls._find_table(roots)
        model = FilteredTableModel(
            all_rows=spec.rows,
            key_column=spec.key_column,
            search_columns=spec.search_columns(),
            table=table,
        )
        return table, model

    @staticmethod
    def _find_table(roots: object) -> TableElement:
        """Descend a one-level GroupElement wrapper to find the built grid."""
        from punt_lux.protocol.elements.group import GroupElement

        assert isinstance(roots, list)
        for root in roots:
            if isinstance(root, TableElement):
                return root
            if isinstance(root, GroupElement):
                for child in root.children:
                    if isinstance(child, TableElement):
                        return child
        msg = "no TableElement found in composition roots"
        raise AssertionError(msg)


class FrameBudget:
    """Measure a callback's mean per-call wall-clock cost against a budget.

    Bundles the three steps every test in this module repeats — time N calls,
    report both the raw wall-clock and the cost normalized per visible unit
    (element or row), assert the mean stays under budget — so each test body
    is the scenario setup plus one ``FrameBudget(...).run(budget)`` call.
    """

    _label: str
    _callback: Callable[[], None]
    _frames: int
    _visible_units: int
    _mean_seconds: float | None
    __slots__ = ("_callback", "_frames", "_label", "_mean_seconds", "_visible_units")

    def __new__(
        cls,
        label: str,
        callback: Callable[[], None],
        *,
        frames: int,
        visible_units: int,
    ) -> Self:
        self = super().__new__(cls)
        self._label = label
        self._callback = callback
        self._frames = frames
        self._visible_units = visible_units
        self._mean_seconds = None
        return self

    def run(self, budget_seconds: float) -> None:
        """Measure, report, and assert the mean per-call cost is under budget."""
        mean_seconds = self._measure()
        self._report(mean_seconds)
        budget_ms = budget_seconds * 1000
        assert mean_seconds < budget_seconds, (
            f"[{self._label}] mean {mean_seconds * 1000:.2f} ms/call over "
            f"{self._visible_units} visible units exceeds {budget_ms:.0f} ms budget"
        )

    def _measure(self) -> float:
        """Run the callback ``_frames`` times and return the mean wall-clock seconds."""
        start = time.perf_counter()
        for _ in range(self._frames):
            self._callback()
        return (time.perf_counter() - start) / self._frames

    def _report(self, mean_seconds: float) -> None:
        """Print the wall-clock and normalized cost so ``pytest -s`` surfaces both.

        Not an assertion channel — ``run``'s budget check carries the
        pass/fail; this is the receipt every subsequent epic fix compares its
        own numbers against.
        """
        per_unit_us = (
            (mean_seconds / self._visible_units) * 1_000_000
            if self._visible_units
            else 0.0
        )
        print(
            f"[{self._label}] mean {mean_seconds * 1000:.3f} ms/frame, "
            f"{self._visible_units} visible units, {per_unit_us:.3f} us/unit"
        )


@pytest.mark.slow
def test_thousand_mixed_elements_render_under_budget_per_frame() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-perf-") as raw_dir:
        log = RecordingLog(Path(raw_dir) / "scene_scale.jsonl")
        factory = RecordingRendererFactory(log)
        elements = MixedSceneBuilder(factory, count=_SCENE_ELEMENT_COUNT).build()

        def render_frame() -> None:
            for elem in elements:
                elem.render()

        FrameBudget(
            "scene-1000-mixed",
            render_frame,
            frames=_SCENE_FRAMES,
            visible_units=_SCENE_ELEMENT_COUNT,
        ).run(_SCENE_BUDGET_SECONDS)


@pytest.mark.slow
def test_ten_thousand_row_table_no_filter_scan_under_budget() -> None:
    """Baseline: the filter scan over the full unfiltered row set."""
    _table, model = TableScaleFixture.build_unfiltered(_TABLE_ROW_COUNT)

    def reproject_empty_search() -> None:
        model.on_search("")

    FrameBudget(
        "table-10k-no-filter",
        reproject_empty_search,
        frames=_TABLE_ITERATIONS,
        visible_units=_TABLE_ROW_COUNT,
    ).run(_TABLE_BUDGET_SECONDS)


@pytest.mark.slow
def test_ten_thousand_row_table_active_filter_scan_under_budget() -> None:
    """The filter scan when a search term reduces ~10k rows to ~100 matches."""
    _table, model = TableScaleFixture.build_unfiltered(_TABLE_ROW_COUNT)
    # Rows are seeded "active" every 100th row (see TableScaleFixture._rows),
    # so searching "active" yields row_count / 100 == _TABLE_FILTERED_ROW_COUNT
    # matches on a 10k-row table.

    def reproject_active_filter() -> None:
        model.on_search("active")

    FrameBudget(
        "table-10k-filtered-100",
        reproject_active_filter,
        frames=_TABLE_ITERATIONS,
        visible_units=_TABLE_ROW_COUNT,
    ).run(_TABLE_BUDGET_SECONDS)

    visible = len(model.visible_ids())
    assert visible == _TABLE_FILTERED_ROW_COUNT, (
        f"fixture drifted: expected {_TABLE_FILTERED_ROW_COUNT} matches, got {visible}"
    )


@pytest.mark.slow
def test_ten_thousand_row_table_multi_selection_scan_under_budget() -> None:
    """The selection-intersect scan on a multi-select 10k-row table.

    Compares zero selections against 100 selections — both are O(rows) today
    via ``TableElement._set_selected_row_ids``'s ``frozenset & self._live_ids()``
    intersect; epic bead #4 (selection scan O(rows) -> O(selected)) is measured
    against whichever of the two costs more before the fix, and both after.
    """
    table, _model = TableScaleFixture.build_unfiltered(_TABLE_ROW_COUNT)
    all_ids = tuple(table.row_id(row) for row in table.rows)
    selected_ids = list(all_ids[:_TABLE_SELECTION_COUNT])

    def patch_zero_selected() -> None:
        table.apply_patch({"selected_row_ids": []})

    def patch_hundred_selected() -> None:
        table.apply_patch({"selected_row_ids": selected_ids})

    FrameBudget(
        "table-10k-select-0",
        patch_zero_selected,
        frames=_TABLE_ITERATIONS,
        visible_units=_TABLE_ROW_COUNT,
    ).run(_TABLE_BUDGET_SECONDS)
    FrameBudget(
        "table-10k-select-100",
        patch_hundred_selected,
        frames=_TABLE_ITERATIONS,
        visible_units=_TABLE_ROW_COUNT,
    ).run(_TABLE_BUDGET_SECONDS)
