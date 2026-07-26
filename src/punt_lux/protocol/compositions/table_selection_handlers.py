"""Hub-side detail-binding handler for a table composition.

``DetailBindingHandler`` patches a sibling detail element from a gesture's anchor
row (the last-interacted row, Decision 2). It runs only on the Hub and is
serializable for the pickled scene blob. The full-selection merge is not a
handler here: ``FilteredTableModel`` observes the table's selection writes
directly, so a gesture *and* an agent ``apply_patch`` both fold into its full
selection through one path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.selection_interaction import RowSelectionChanged
    from punt_lux.protocol.elements.markdown import MarkdownElement

__all__ = ["DetailBindingHandler"]


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
        self.render_anchor(event.anchor)

    def render_anchor(self, anchor: str) -> None:
        """Patch the detail region to ``anchor``'s card, or the placeholder.

        Called on a selection gesture and by ``FilteredTableModel`` after a filter
        re-projection reseats the anchor, so the panel never keeps showing a row
        the filter has hidden.
        """
        content = self._content_by_id.get(anchor, self._placeholder)
        self._detail.apply_patch({"content": content})
