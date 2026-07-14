"""PatchBatch.from_wire — the boundary that turns raw update dicts into requests.

``from_wire`` is the single place the wire shape becomes typed domain requests,
so it is where malformed patches must be rejected loud rather than silently
reshaped. The two shapes — a removal (``remove`` is boolean ``True``) and a
field set (a ``set`` mapping) — are mutually exclusive within a patch and across
the batch (an id may not be both set and removed); every other combination raises
``MalformedPatchError``.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.patch_batch import PatchBatch
from punt_lux.domain.hub.write_errors import MalformedPatchError
from punt_lux.domain.ids import ElementId


def test_plain_removal_is_parsed() -> None:
    """A bare ``{"remove": true}`` yields one removal and no field patches."""
    batch = PatchBatch.from_wire([{"id": "x", "remove": True}])

    assert batch.removals == (ElementId("x"),)
    assert batch.field_patches == ()


def test_plain_set_is_parsed() -> None:
    """A bare ``{"set": {...}}`` yields one field patch and no removals."""
    batch = PatchBatch.from_wire([{"id": "x", "set": {"content": "hi"}}])

    assert batch.removals == ()
    assert len(batch.field_patches) == 1
    patch = batch.field_patches[0]
    assert patch.element_id == ElementId("x")
    assert dict(patch.fields) == {"content": "hi"}


def test_remove_and_set_together_is_rejected() -> None:
    """A patch carrying both ``remove`` and ``set`` is refused, never silently
    dropping the ``set``."""
    with pytest.raises(MalformedPatchError, match="mutually exclusive"):
        PatchBatch.from_wire([{"id": "x", "remove": True, "set": {"content": "hi"}}])


def test_non_boolean_truthy_remove_is_rejected() -> None:
    """A truthy but non-boolean ``remove`` (``"yes"``) is refused, not treated
    as a removal."""
    with pytest.raises(MalformedPatchError, match="must be the boolean true"):
        PatchBatch.from_wire([{"id": "x", "remove": "yes"}])


def test_integer_truthy_remove_is_rejected() -> None:
    """A truthy integer ``remove`` (``1``) is also refused — only ``True`` counts."""
    with pytest.raises(MalformedPatchError, match="must be the boolean true"):
        PatchBatch.from_wire([{"id": "x", "remove": 1}])


def test_falsy_remove_with_no_set_is_rejected() -> None:
    """A falsy ``remove`` and no ``set`` is neither shape — refused."""
    with pytest.raises(MalformedPatchError, match="neither a truthy 'remove'"):
        PatchBatch.from_wire([{"id": "x", "remove": False}])


def test_string_patch_entry_is_rejected() -> None:
    """A bare string in the patch list is refused loud, not crashed on ``.get``."""
    with pytest.raises(MalformedPatchError, match="must be a mapping"):
        PatchBatch.from_wire(["oops"])


def test_integer_patch_entry_is_rejected() -> None:
    """A scalar integer entry is refused before any field lookup."""
    with pytest.raises(MalformedPatchError, match="must be a mapping"):
        PatchBatch.from_wire([123])


def test_missing_id_is_rejected() -> None:
    """A patch with no ``id`` is refused before any shape check."""
    with pytest.raises(MalformedPatchError, match="must be a non-empty string"):
        PatchBatch.from_wire([{"set": {"content": "hi"}}])


def test_non_string_id_is_rejected() -> None:
    """A non-string ``id`` (``1``) is refused, never coerced to element ``"1"``."""
    with pytest.raises(MalformedPatchError, match="must be a non-empty string"):
        PatchBatch.from_wire([{"id": 1, "set": {"content": "hi"}}])


def test_empty_string_id_is_rejected() -> None:
    """An empty ``id`` is refused — it addresses no element."""
    with pytest.raises(MalformedPatchError, match="must be a non-empty string"):
        PatchBatch.from_wire([{"id": "", "set": {"content": "hi"}}])


def test_non_empty_string_id_is_accepted() -> None:
    """A well-formed non-empty string ``id`` parses to that element."""
    batch = PatchBatch.from_wire([{"id": "x", "set": {"content": "hi"}}])

    assert batch.field_patches[0].element_id == ElementId("x")


def test_same_id_set_then_remove_across_entries_is_rejected() -> None:
    """An id set in one entry and removed in another is refused — the cross-entry
    form of the within-a-patch exclusivity, never collapsed to a bare remove."""
    with pytest.raises(MalformedPatchError, match="both set and removed"):
        PatchBatch.from_wire(
            [{"id": "x", "set": {"content": "hi"}}, {"id": "x", "remove": True}]
        )


def test_same_id_remove_then_set_across_entries_is_rejected() -> None:
    """Order does not matter: remove-then-set conflicts as set-then-remove does."""
    with pytest.raises(MalformedPatchError, match="both set and removed"):
        PatchBatch.from_wire(
            [{"id": "x", "remove": True}, {"id": "x", "set": {"content": "hi"}}]
        )


def test_distinct_ids_one_set_one_remove_are_both_kept() -> None:
    """One id set and a DIFFERENT id removed is not a conflict — both survive."""
    batch = PatchBatch.from_wire(
        [{"id": "a", "set": {"content": "hi"}}, {"id": "b", "remove": True}]
    )

    assert batch.removals == (ElementId("b"),)
    assert [p.element_id for p in batch.field_patches] == [ElementId("a")]


def test_same_id_set_twice_merges_without_a_false_conflict() -> None:
    """Two set entries for one id merge — no removal in play, so no conflict."""
    batch = PatchBatch.from_wire(
        [{"id": "x", "set": {"a": 1}}, {"id": "x", "set": {"b": 2}}]
    )

    assert batch.removals == ()
    assert dict(batch.field_patches[0].fields) == {"a": 1, "b": 2}


def test_same_id_removed_twice_dedupes_without_a_false_conflict() -> None:
    """Two remove entries for one id dedupe to a single removal — no conflict."""
    batch = PatchBatch.from_wire(
        [{"id": "x", "remove": True}, {"id": "x", "remove": True}]
    )

    assert batch.removals == (ElementId("x"),)
    assert batch.field_patches == ()
