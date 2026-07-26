"""The table's selection arbiter — index↔row_id translation and the fire decision.

ImGui keys a multi-select by an integer ``SelectionUserData``; a Lux table keys
by a stable string ``row_id``. This arbiter is the pure translation between the
two, plus the "did the user change the selection?" decision — the fragile part —
kept out of the ImGui adapter so it is testable without a live frame.

The renderer tags each row with its *current display-order index* each frame, so
the mapping is rebuilt per frame and composes with a Display-local sort. The
membership set is unordered; the *anchor* is ImGui's last-interacted item
(``range_src_item``), never read off set order.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["TableRowSelection"]


@final
class TableRowSelection:
    """Translate a frame's display order between selection indices and row ids."""

    _display_ids: tuple[str, ...]
    __slots__ = ("_display_ids",)

    def __new__(cls, display_ids: tuple[str, ...]) -> Self:
        self = super().__new__(cls)
        self._display_ids = display_ids
        return self

    @property
    def item_count(self) -> int:
        """Return the number of rows in the current display order."""
        return len(self._display_ids)

    def ids_for(self, selected_indices: frozenset[int]) -> frozenset[str]:
        """Return the row ids for a set of display-order indices."""
        return frozenset(
            self._display_ids[i]
            for i in selected_indices
            if 0 <= i < len(self._display_ids)
        )

    def anchor_for(self, range_src: int, selected: frozenset[str]) -> str:
        """Return the anchor row id — ImGui's last-interacted item, else a survivor.

        ``range_src`` is ``MultiSelectIO.range_src_item`` (the last row the user
        touched). When it names a selected row that row is the anchor; otherwise
        the anchor falls back to the least selected id, or ``""`` when empty.
        """
        if 0 <= range_src < len(self._display_ids):
            candidate = self._display_ids[range_src]
            if candidate in selected:
                return candidate
        return min(selected) if selected else ""

    def is_user_change(
        self, new_ids: frozenset[str], authoritative: frozenset[str]
    ) -> bool:
        """Return whether the gesture changed the selection from the Hub's value.

        The frame seeds the storage from ``authoritative``, so a selection that
        still equals it is the echo of the Hub value (or no gesture) and must not
        fire; anything else is a genuine user change.
        """
        return new_ids != authoritative
