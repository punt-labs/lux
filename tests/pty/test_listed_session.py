"""Only a row with a non-empty string id, label and state names a session."""

from __future__ import annotations

import pytest

from punt_lux.pty.listed_session import ListedSession


def test_a_well_formed_row_is_kept_with_its_fields() -> None:
    [row] = ListedSession.well_formed(
        [{"session": "s1", "label": "Terminal", "state": "running"}]
    )
    assert (row.session, row.label, row.is_running) == ("s1", "Terminal", True)


def test_a_row_in_another_state_is_not_running() -> None:
    [row] = ListedSession.well_formed(
        [{"session": "s1", "label": "Terminal", "state": "exited"}]
    )
    assert not row.is_running


@pytest.mark.parametrize(
    "row",
    [
        "junk",
        {"label": "T", "state": "running"},
        {"session": "", "label": "T", "state": "running"},
        {"session": 7, "label": "T", "state": "running"},
        {"session": "s", "label": None, "state": "running"},
        {"session": "s", "label": "T", "state": None},
    ],
)
def test_a_malformed_row_is_ignored(row: object) -> None:
    assert ListedSession.well_formed([row]) == []


@pytest.mark.parametrize("session", ["", None, 7])
def test_construction_refuses_an_unusable_session_id(session: object) -> None:
    with pytest.raises(ValueError, match="session"):
        ListedSession(session, "Terminal", "running")


@pytest.mark.parametrize("field", ["label", "state"])
def test_construction_refuses_a_non_string_label_or_state(field: str) -> None:
    fields: dict[str, object] = {"session": "s1", "label": "T", "state": "running"}
    fields[field] = None
    with pytest.raises(ValueError, match=field):
        ListedSession(**fields)
