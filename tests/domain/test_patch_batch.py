"""PatchBatch.from_wire — the boundary that turns raw update dicts into requests.

``from_wire`` is the single place the wire shape becomes typed domain requests,
so it is where malformed patches must be rejected loud rather than silently
reshaped. The two shapes — a removal (``remove`` is boolean ``True``) and a
field set (a ``set`` mapping) — are mutually exclusive; every other combination
raises ``MalformedPatchError``.
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


def test_missing_id_is_rejected() -> None:
    """A patch with no ``id`` is refused before any shape check."""
    with pytest.raises(MalformedPatchError, match="missing a required 'id'"):
        PatchBatch.from_wire([{"set": {"content": "hi"}}])
