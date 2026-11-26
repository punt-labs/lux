"""The listing answers which session runs, and which holds a label."""

from __future__ import annotations

import pytest

from punt_lux.pty.daemon_exchange import SessionRefusedError
from punt_lux.pty.session_listing import SessionListing

RUNNING: dict[str, object] = {"session": "s1", "label": "Terminal", "state": "running"}
ENDED: dict[str, object] = {"session": "s2", "label": "Build", "state": "exited"}


def test_a_listed_running_session_is_running() -> None:
    assert SessionListing({"sessions": [RUNNING, ENDED]}).is_running("s1")


def test_an_ended_or_unlisted_session_is_not_running() -> None:
    listing = SessionListing({"sessions": [RUNNING, ENDED]})
    assert not listing.is_running("s2")
    assert not listing.is_running("")


def test_the_running_session_under_a_label_is_found() -> None:
    listing = SessionListing({"sessions": [ENDED, RUNNING]})
    assert listing.running_under("Terminal") == "s1"
    assert listing.running_under("Build") == ""


def test_entries_that_are_not_mappings_are_ignored() -> None:
    assert SessionListing({"sessions": ["junk", 3, RUNNING]}).is_running("s1")


@pytest.mark.parametrize("sessions", [None, "s1", {}])
def test_a_reply_without_a_list_is_refused(sessions: object) -> None:
    with pytest.raises(SessionRefusedError, match="without sessions"):
        SessionListing({"sessions": sessions})
