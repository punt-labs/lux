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


def _view_roots(*ids: object) -> InspectionView:
    """Build an InspectionView whose top-level ``elements`` carry ``ids``."""
    roots = [{"id": eid, "kind": "sep", "props": {}} for eid in ids]
    return InspectionView({"element_paths": [], "elements": roots})


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


def test_ids_returns_the_named_ids() -> None:
    """``ids`` collects every named element id present."""
    view = _view("a", "b", "c")

    assert view.ids() == frozenset({"a", "b", "c"})


def test_ids_filters_non_string_ids() -> None:
    """A non-string id (a malformed record) never leaks into ``frozenset[str]``.

    ``cast`` would reclassify ``None`` as ``str`` without coercing it, so the
    isinstance filter is what keeps the advertised element type honest.
    """
    view = _view("a", None, "b")

    result = view.ids()
    assert result == frozenset({"a", "b"})
    assert all(isinstance(eid, str) for eid in result)


def test_ids_excludes_the_anonymous_sentinel() -> None:
    """The empty-id sentinel (an anonymous element) is not a named id."""
    view = _view("", "a", "")

    assert view.ids() == frozenset({"a"})


def test_root_ids_filters_non_string_ids() -> None:
    """A non-string root id (a malformed record) never leaks into the roots.

    ``cast`` would reclassify the value as ``str`` without coercing it, so the
    isinstance filter is what keeps the advertised ``tuple[str, ...]`` honest.
    """
    view = _view_roots("r1", None, "r2")

    result = view.root_ids()
    assert result == frozenset({"r1", "r2"})
    assert all(isinstance(rid, str) for rid in result)


def test_root_ids_keeps_the_anonymous_sentinel() -> None:
    """The empty-string id of an anonymous root is kept, unlike ``ids``.

    An anonymous root carries the empty-id sentinel; the shape check needs it
    in the root set, so the filter tests only for ``str``, not truthiness.
    """
    view = _view_roots("", "r1")

    assert view.root_ids() == frozenset({"", "r1"})
