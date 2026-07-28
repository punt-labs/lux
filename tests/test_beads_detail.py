"""Unit tests for BeadsDetail — the detail-pane markdown composer."""

from __future__ import annotations

from typing import Any

from punt_lux.apps.beads_detail import BeadsDetail

_ISSUE: dict[str, Any] = {
    "id": "beads-001",
    "title": "Fix login bug",
    "status": "open",
    "priority": 1,
    "issue_type": "bug",
    "description": "Login fails on slow networks.",
    "owner": "bob",
    "created_at": "2026-03-01T00:00:00Z",
    "updated_at": "2026-03-09T12:00:00Z",
}


def _body(issue: dict[str, Any]) -> str:
    detail = BeadsDetail.for_issues([issue])
    body = detail["body"]
    assert isinstance(body, list)
    return str(body[0])


def test_for_issues_leaves_fields_and_rows_empty() -> None:
    # The composed markdown is the whole body; the generic field/value rendering
    # is left empty so it adds nothing inline.
    detail = BeadsDetail.for_issues([_ISSUE])
    assert detail["fields"] == []
    assert detail["rows"] == []
    assert len(detail["body"]) == 1


def test_body_separates_the_metadata_table_from_the_description() -> None:
    table, sep, description = _body(_ISSUE).partition("\n\n---\n\n")
    assert sep  # a horizontal rule divides the two regions
    assert table.startswith("| Field | Value |\n| --- | --- |")
    assert "| ID | beads-001 |" in table
    assert "| Priority | P1 |" in table
    assert description == "Login fails on slow networks."


def test_dates_are_truncated_to_the_day() -> None:
    table, _, _ = _body(_ISSUE).partition("\n\n---\n\n")
    assert "| Created | 2026-03-01 |" in table
    assert "| Updated | 2026-03-09 |" in table


def test_empty_description_degrades_to_a_placeholder() -> None:
    _, sep, description = _body({**_ISSUE, "description": ""}).partition("\n\n---\n\n")
    assert sep
    assert description == "_No description._"


def test_empty_owner_reads_as_unassigned() -> None:
    assert "| Owner | unassigned |" in _body({**_ISSUE, "owner": ""})


def test_a_pipe_in_a_cell_value_is_escaped() -> None:
    # A literal pipe in free-ish assignee text would split the row into extra
    # columns; escaping keeps it inside one cell, table intact.
    body = _body({**_ISSUE, "owner": "a|b"})
    assert "| Owner | a\\|b |" in body


def test_for_issues_body_is_parallel_to_the_input() -> None:
    detail = BeadsDetail.for_issues([_ISSUE, {**_ISSUE, "id": "beads-002"}])
    body = detail["body"]
    assert isinstance(body, list)
    assert len(body) == 2
    assert "beads-002" in str(body[1])
