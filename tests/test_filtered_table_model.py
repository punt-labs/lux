"""``FilteredTableModel`` filter-scan memoization (lux-qfzu.3).

``_visible_rows`` caches its result by ``(rows identity, filter state)``; these
tests drive the cache through a real ``_matches_search``/``_matches_combos``
scan (via monkeypatch counters) rather than asserting on wall-clock, per
``tests/CLAUDE.md``'s guidance against timing-sensitive assertions in the
default gate.
"""

from __future__ import annotations

from typing import Any, Self

from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
from punt_lux.protocol.elements.table import TableElement


def _bound(
    rows: tuple[tuple[object, ...], ...],
) -> tuple[TableElement, FilteredTableModel]:
    table = TableElement(
        id="t", columns=("ID", "Status"), rows=rows, selection_mode="multi"
    )
    model = FilteredTableModel(
        all_rows=rows, key_column=0, search_columns=(1,), table=table
    )
    return table, model


def _rows(n: int) -> tuple[tuple[object, ...], ...]:
    return tuple((f"r{i}", "active" if i % 2 == 0 else "idle") for i in range(n))


class _ScanCounter:
    """Counts real filter-predicate scans, monkeypatched over ``_matches_search``."""

    _calls: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._calls = 0
        return self

    @property
    def calls(self) -> int:
        return self._calls

    @calls.setter
    def calls(self, value: int) -> None:
        self._calls = value

    def wrap(self, model: FilteredTableModel, monkeypatch: Any) -> None:
        original = model._matches_search

        def counting(row: tuple[object, ...], needle: str) -> bool:
            self._calls += 1
            return original(row, needle)

        monkeypatch.setattr(model, "_matches_search", counting)


class TestCacheHitOnUnchangedInput:
    def test_repeat_reproject_with_no_change_does_not_rescan(
        self, monkeypatch: Any
    ) -> None:
        _table, model = _bound(_rows(10))
        counter = _ScanCounter()
        counter.wrap(model, monkeypatch)

        model.on_search("active")
        first_calls = counter.calls
        assert first_calls > 0

        # Calling the memoized accessor again with nothing changed must not
        # re-scan — the second visible_ids() call costs zero predicate calls.
        model.visible_ids()
        assert counter.calls == first_calls

    def test_cached_result_is_returned_by_identity(self) -> None:
        _table, model = _bound(_rows(10))
        model.on_search("active")
        first = model._visible_rows()
        second = model._visible_rows()
        assert first is second


class TestInvalidateOnRowsChange:
    def test_dataset_refresh_forces_a_rescan(self, monkeypatch: Any) -> None:
        table, model = _bound(_rows(10))
        counter = _ScanCounter()
        counter.wrap(model, monkeypatch)

        model.on_search("active")
        assert counter.calls > 0  # sanity: the first search did scan

        # The dataset refresh itself re-projects (and thus rescans) internally;
        # the invariant under test is that the NEW dataset drives a real scan
        # rather than silently returning a stale cached result.
        counter.calls = 0
        table.apply_patch({"rows": [list(r) for r in _rows(12)]})
        assert counter.calls > 0  # rows changed -> cache invalidated, real scan


class TestInvalidateOnFilterChange:
    def test_new_search_term_forces_a_rescan(self, monkeypatch: Any) -> None:
        _table, model = _bound(_rows(10))
        counter = _ScanCounter()
        counter.wrap(model, monkeypatch)

        model.on_search("active")
        counter.calls = 0
        model.on_search("idle")
        assert counter.calls > 0

    def test_combo_pick_forces_a_rescan(self, monkeypatch: Any) -> None:
        _table, model = _bound(_rows(10))
        counter = _ScanCounter()
        counter.wrap(model, monkeypatch)

        model.on_search("active")
        counter.calls = 0
        model.on_combo(1, "idle")
        assert counter.calls > 0


class TestCorrectnessVsBaseline:
    def test_filtered_output_matches_the_unmemoized_predicate_scan(self) -> None:
        rows = _rows(50)
        _table, model = _bound(rows)
        model.on_search("active")

        expected = frozenset(row[0] for row in rows if "active" in str(row[1]).lower())
        assert model.visible_ids() == expected

    def test_clearing_the_filter_restores_all_rows(self) -> None:
        rows = _rows(6)
        _table, model = _bound(rows)
        model.on_search("active")
        assert len(model.visible_ids()) < len(rows)
        model.on_search("")
        assert model.visible_ids() == frozenset(row[0] for row in rows)
