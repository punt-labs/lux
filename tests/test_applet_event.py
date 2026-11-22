"""Safe launch-record vocabulary, severity, and child correlation."""

from __future__ import annotations

import logging

import pytest

from punt_lux.service.applet_event import AppletEvent, AppletRecords


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (AppletEvent.INTENT, "launch intent: spawning"),
        (AppletEvent.LAUNCHED, "launched: spawned"),
        (AppletEvent.MISSING, "skipped: executable missing"),
        (AppletEvent.RUNNING, "skipped: already running"),
        (AppletEvent.PROBE_ERROR, "failed: process probe error"),
        (AppletEvent.SPAWN_ERROR, "failed: spawn error"),
    ],
)
def test_safe_event_vocabulary(
    caplog: pytest.LogCaptureFixture, event: AppletEvent, message: str
) -> None:
    with caplog.at_level(logging.INFO):
        AppletRecords.record(event, 456)
    suffix = (
        " (child pid=456)"
        if event in (AppletEvent.LAUNCHED, AppletEvent.SPAWN_ERROR)
        else ""
    )
    assert caplog.messages == [f"SessionStart applet {message}{suffix}"]
    assert caplog.records[0].levelno == (
        logging.WARNING
        if event in (AppletEvent.PROBE_ERROR, AppletEvent.SPAWN_ERROR)
        else logging.INFO
    )


@pytest.mark.parametrize("event", list(AppletEvent))
def test_absent_child_is_omitted(
    caplog: pytest.LogCaptureFixture, event: AppletEvent
) -> None:
    with caplog.at_level(logging.INFO):
        AppletRecords.record(event, 0)
    assert "child pid" not in caplog.messages[0]
