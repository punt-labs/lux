"""Typed row-selection event for the Hub-authoritative table selection.

A ``table`` routes one selection gesture down the same remote-dispatch path as
``ButtonClicked``: the Hub records the new selection set and re-pushes. Unlike a
``tab_bar``'s single ``tab_id``, a table selection is a *set* of stable
``row_id``s plus an explicit *anchor* — the last-interacted row, taken from
ImGui's ``MultiSelectIO``, never inferred from the (unordered) set's order. Kept
in its own module because a table is a leaf, not a container, and
``container_interaction`` already holds three classes (PY-OO-2 cap).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.domain.event_payload import EventPayload
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.wire_value import WireValue

__all__ = ["RowSelectionChanged"]


@dataclass(frozen=True, slots=True, init=False)
class RowSelectionChanged:
    """A typed row-selection-change event for a ``table``.

    ``row_ids`` is the full visible selection after the gesture — an unordered
    set, tuple only for wire shape; a range/box gesture changes many rows in one
    act, so one absolute event per gesture is correct. ``anchor`` is the
    last-interacted row's ``row_id`` (``""`` when the selection is empty), carried
    explicitly because ImGui — not the set — knows which row the user last
    touched. Same ``init=False`` + ``__new__`` construction as the leaf events.
    """

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    row_ids: tuple[str, ...]
    anchor: str
    kind: ClassVar[Literal["row_selection_changed"]] = "row_selection_changed"

    def __new__(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        row_ids: tuple[str, ...],
        anchor: str,
    ) -> Self:
        self = object.__new__(cls)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "element_id", element_id)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "row_ids", row_ids)
        object.__setattr__(self, "anchor", anchor)
        return self

    @classmethod
    def from_wire(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> Self:
        """Build the selection event; the payload carries the set and the anchor.

        The wire payload is a mapping ``{"row_ids": [str, ...], "anchor": str}``:
        the full new selection plus the last-interacted row. A set carries more
        than one id, so unlike the scalar ``ValueChanged`` payload it cannot ride
        as a bare value — the anchor would have nowhere to go.
        """
        payload = WireValue(value, scene_id=scene_id, element_id=element_id).as_mapping(
            "a row_selection_changed payload (mapping)"
        )
        return cls(
            scene_id=scene_id,
            element_id=element_id,
            owner_id=owner_id,
            row_ids=payload.field("row_ids").as_string_tuple(
                "row_ids as a list of strings"
            ),
            anchor=payload.field("anchor", "").as_str("anchor as a string"),
        )

    def to_payload(self) -> Mapping[str, object]:
        """Return the published payload: identity, the selection, and the anchor.

        ``row_ids`` becomes a list because the payload crosses to the agent as
        JSON, which has no tuple. The anchor is what a subscriber acting on one
        row reads — the row the user just touched, which the unordered set cannot
        name.
        """
        return EventPayload.of(self, self.kind).to_mapping(
            row_ids=list(self.row_ids), anchor=self.anchor
        )
