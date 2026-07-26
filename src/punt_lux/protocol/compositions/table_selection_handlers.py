"""Hub-side selection handlers for a table composition — merge and detail-bind.

Both are extra ``RowSelectionChanged`` handlers on the composition's table,
beside the table's built-in selection state-sync. ``SelectionMergeHandler`` keeps
``FilteredTableModel``'s full selection current across hidden rows;
``DetailBindingHandler`` patches a sibling detail element from the gesture's
anchor row (the last-interacted row, Decision 2). Both run only on the Hub and
are serializable for the pickled scene blob.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.selection_interaction import RowSelectionChanged
    from punt_lux.protocol.compositions.filtered_table_model import FilteredTableModel
    from punt_lux.protocol.elements.markdown import MarkdownElement

__all__ = ["DetailBindingHandler", "SelectionMergeHandler"]


class SelectionMergeHandler:
    """Merge a user's visible selection into the model's full selection."""

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
    def __call__(self, event: RowSelectionChanged) -> None:
        self._model.on_selection_gesture(frozenset(event.row_ids))


class DetailBindingHandler:
    """Patch a sibling detail element from the gesture's anchor row.

    Holds the detail element and a per-row-id detail-content map, so the anchor's
    content is shown; an anchor with no detail (or an empty selection) falls back
    to the placeholder prompt.
    """

    _detail: MarkdownElement
    _content_by_id: dict[str, str]
    _placeholder: str

    def __new__(
        cls,
        detail: MarkdownElement,
        *,
        content_by_id: dict[str, str],
        placeholder: str,
    ) -> Self:
        self = super().__new__(cls)
        self._detail = detail
        self._content_by_id = content_by_id
        self._placeholder = placeholder
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (
            object.__new__,
            (type(self),),
            {
                "_detail": self._detail,
                "_content_by_id": self._content_by_id,
                "_placeholder": self._placeholder,
            },
        )

    def __setstate__(self, state: dict[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @trace
    def __call__(self, event: RowSelectionChanged) -> None:
        content = self._content_by_id.get(event.anchor, self._placeholder)
        self._detail.apply_patch({"content": content})
