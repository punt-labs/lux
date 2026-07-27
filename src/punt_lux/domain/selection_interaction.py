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
from typing import ClassVar, Literal, Self, cast

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction_errors import WrongKindError

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
        if not isinstance(value, Mapping):
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected="a row_selection_changed payload (mapping)",
                got=type(value).__name__,
            )
        payload = cast("Mapping[str, object]", value)
        row_ids = cls._require_id_tuple(scene_id, element_id, payload.get("row_ids"))
        anchor = cls._require_anchor(scene_id, element_id, payload.get("anchor", ""))
        return cls(
            scene_id=scene_id,
            element_id=element_id,
            owner_id=owner_id,
            row_ids=row_ids,
            anchor=anchor,
        )

    @staticmethod
    def _require_id_tuple(
        scene_id: SceneId, element_id: ElementId, raw: object
    ) -> tuple[str, ...]:
        """Return ``raw`` as a tuple of row-id strings or raise ``WrongKindError``."""
        got = type(raw).__name__
        if isinstance(raw, list) and all(
            isinstance(item, str) for item in cast("list[object]", raw)
        ):
            return tuple(cast("list[str]", raw))
        raise WrongKindError(
            scene_id=scene_id,
            element_id=element_id,
            expected="row_ids as a list of strings",
            got=got,
        )

    @staticmethod
    def _require_anchor(scene_id: SceneId, element_id: ElementId, raw: object) -> str:
        """Return ``raw`` as the anchor string or raise ``WrongKindError``."""
        if not isinstance(raw, str):
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected="anchor as a string",
                got=type(raw).__name__,
            )
        return raw
