"""The listing answers which session runs, and which holds a label."""

from __future__ import annotations

import pytest

from punt_lux.pty.daemon_exchange import SessionRefusedError
from punt_lux.pty.session_listing import SessionListing

RUNNING: dict[str, object] = {"session": "s1", "label": "Terminal", "state": "running"}
ENDED: dict[str, object] = {"session": "s2", "label": "Build", "state": "exited"}


def test_a_listed_running_session_is_running() -> None:
    assert SessionListing.from_result({"sessions": [RUNNING, ENDED]}).is_running("s1")


def test_an_ended_or_unlisted_session_is_not_running() -> None:
    listing = SessionListing.from_result({"sessions": [RUNNING, ENDED]})
    assert not listing.is_running("s2")
    assert not listing.is_running("")


def test_the_running_session_under_a_label_is_found() -> None:
    listing = SessionListing.from_result({"sessions": [ENDED, RUNNING]})
    assert listing.running_under("Terminal") == "s1"
    assert listing.running_under("Build") == ""


def test_entries_that_are_not_mappings_are_ignored() -> None:
    assert SessionListing.from_result({"sessions": ["junk", 3, RUNNING]}).is_running(
        "s1"
    )


@pytest.mark.parametrize("sessions", [None, "s1", {}])
def test_a_reply_without_a_list_is_refused(sessions: object) -> None:
    with pytest.raises(SessionRefusedError, match="without sessions"):
        SessionListing.from_result({"sessions": sessions})


@pytest.mark.parametrize("session", [None, "", 7, ["s1"]])
def test_a_row_without_a_usable_session_id_is_ignored(session: object) -> None:
    row = {"session": session, "label": "Terminal", "state": "running"}
    listing = SessionListing.from_result({"sessions": [row]})
    assert listing.running_under("Terminal") == ""
    assert not listing.is_running(str(session))


def test_a_row_missing_its_session_or_state_is_ignored() -> None:
    no_session = {"label": "Terminal", "state": "running"}
    no_state = {"session": "s9", "label": "Terminal"}
    listing = SessionListing.from_result({"sessions": [no_session, no_state]})
    assert listing.running_under("Terminal") == ""
    assert not listing.is_running("None")


def test_the_listing_is_a_snapshot_of_the_result_it_was_built_from() -> None:
    sessions: list[object] = [RUNNING]
    result: dict[str, object] = {"sessions": sessions}
    listing = SessionListing.from_result(result)
    sessions.clear()
    assert listing.is_running("s1")


def test_the_listing_is_a_snapshot_of_the_mapping_it_was_handed() -> None:
    running = {"s1": "Terminal"}
    listing = SessionListing(running)
    running.clear()
    assert listing.running_under("Terminal") == "s1"
