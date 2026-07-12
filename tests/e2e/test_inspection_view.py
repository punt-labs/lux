"""Unit coverage for InspectionView's shape queries.

``duplicate_ids`` guards the re-push invariant: a named element must appear
once across ``element_paths``, never both nested and hoisted to a root. But
anonymous elements (the empty-id sentinel — bare separators) carry no
identity and may repeat freely, so their colliding empty ids must not read
as duplicates. These tests pin that the anonymous exemption holds and that
a genuine named duplicate is still caught.
"""

from __future__ import annotations

from .inspection_view import InspectionView


def _view(*ids: object) -> InspectionView:
    """Build an InspectionView whose element_paths carry ``ids`` in order."""
    records = [
        {"id": eid, "kind": "sep", "render_path": "", "props": {}} for eid in ids
    ]
    return InspectionView({"element_paths": records, "elements": []})


def test_repeated_anonymous_ids_are_not_duplicates() -> None:
    """Several empty-id separators do not register a false duplicate."""
    view = _view("", "a", "", "b", "")

    assert view.duplicate_ids() == frozenset()


def test_repeated_named_id_is_a_duplicate() -> None:
    """A named id appearing twice is reported as a duplicate."""
    view = _view("a", "b", "a")

    assert view.duplicate_ids() == frozenset({"a"})


def test_named_duplicate_caught_amid_anonymous_repeats() -> None:
    """A named duplicate surfaces even when anonymous ids repeat around it."""
    view = _view("", "dup", "", "dup", "")

    assert view.duplicate_ids() == frozenset({"dup"})


def test_non_string_and_empty_ids_never_count() -> None:
    """A missing/non-string id is skipped, not counted as a repeat."""
    view = _view(None, None, "", "")

    assert view.duplicate_ids() == frozenset()
