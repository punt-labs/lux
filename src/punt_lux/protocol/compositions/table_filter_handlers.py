"""Hub-side filter handlers for a table composition — search and combo.

Each is an extra ``ValueChanged`` handler on the composition's search
``input_text`` / status ``combo``, beside that element's built-in value mirror.
On the Hub the handler drives ``FilteredTableModel`` to recompute the visible
rows and re-project the selection; on the Display ``wrap_handlers_for_remote``
folds it into the remote-dispatch group, so it runs only on the authoritative
Hub copy. Both are serializable so they travel in the pickled scene blob.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.interaction import ValueChanged
    from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel

__all__ = ["ComboFilterHandler", "SearchFilterHandler"]


class SearchFilterHandler:
    """Drive the model's search term from a search ``input_text``'s value."""

    _model: FilteredTableModel

    def __new__(cls, model: FilteredTableModel) -> Self:
        self = super().__new__(cls)
        self._model = model
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (object.__new__, (type(self),), {"_model": self._model})

    def __setstate__(self, state: dict[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @trace
    def __call__(self, event: ValueChanged) -> None:
        self._model.on_search(str(event.value))


class ComboFilterHandler:
    """Drive a categorical filter from a status ``combo``'s selected index.

    Holds the column the combo filters and its items, so the selected *index*
    maps to the chosen category (``"All"`` clears the filter).
    """

    _model: FilteredTableModel
    _column: int
    _items: tuple[str, ...]

    def __new__(
        cls, model: FilteredTableModel, *, column: int, items: tuple[str, ...]
    ) -> Self:
        self = super().__new__(cls)
        self._model = model
        self._column = column
        self._items = items
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (
            object.__new__,
            (type(self),),
            {"_model": self._model, "_column": self._column, "_items": self._items},
        )

    def __setstate__(self, state: dict[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @trace
    def __call__(self, event: ValueChanged) -> None:
        # A combo's value is a selected index. bool subclasses int, so an errant
        # ValueChanged(value=True) would read as index 1 — guard it out (the same
        # bool exclusion the wire decoders use) so a non-index falls back to 0.
        raw = event.value
        index = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
        chosen = self._items[index] if 0 <= index < len(self._items) else "All"
        self._model.on_combo(self._column, chosen)
