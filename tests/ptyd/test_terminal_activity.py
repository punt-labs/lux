"""A live terminal keeps the render loop awake; an absent one lets it idle."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from punt_lux.display.terminal.activity import TerminalActivity
from punt_lux.display.terminal.idling_decision import IdlingDecision
from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.remote_pool import RemotePool
from punt_lux.display.terminal.remote_sessions import RemoteSessions

LONG_QUIET_S = 5.0


def _idling_after_pump(
    phase: RemotePhase | None, *, busy: bool, quiet_for: float
) -> bool:
    now = 100.0 + quiet_for
    pool = RemotePool(Path("/nonexistent/luxd-pty.sock"))
    if phase is not None:
        session = pool.get("t1", "sh")
        session._phase = phase
        with patch("punt_lux.display.terminal.remote.time.monotonic", return_value=now):
            session.mark_shown()  # on screen this frame
    params = SimpleNamespace(fps_idling=SimpleNamespace(enable_idling=True))
    with (
        patch.object(RemoteSessions, "_pool", pool),
        patch.object(RemotePool, "pump", return_value=busy),
        patch.object(pool, "_last_output_at", 100.0),
        patch(
            "punt_lux.display.terminal.remote_pool.time.monotonic",
            return_value=now,
        ),
        patch(
            "punt_lux.display.terminal.activity.hello_imgui.get_runner_params",
            return_value=params,
        ),
    ):
        TerminalActivity.pump()
    idling: bool = params.fps_idling.enable_idling
    return idling


@pytest.mark.parametrize("phase", [RemotePhase.READY, RemotePhase.SNAPSHOT])
def test_live_session_stays_awake_through_a_quiet_gap(phase: RemotePhase) -> None:
    assert not _idling_after_pump(phase, busy=False, quiet_for=LONG_QUIET_S)


def test_no_session_idles_after_quiet() -> None:
    assert _idling_after_pump(None, busy=False, quiet_for=LONG_QUIET_S)


def test_no_session_stays_awake_just_after_output() -> None:
    assert not _idling_after_pump(None, busy=False, quiet_for=0.1)


@pytest.mark.parametrize(
    "phase",
    [
        RemotePhase.CONNECTING,
        RemotePhase.EXITED,
        RemotePhase.DISCONNECTED,
        RemotePhase.FAILED,
        RemotePhase.CLOSED,
    ],
)
def test_non_live_session_idles_after_quiet(phase: RemotePhase) -> None:
    assert _idling_after_pump(phase, busy=False, quiet_for=LONG_QUIET_S)


def test_bytes_this_frame_keep_the_loop_awake() -> None:
    assert not IdlingDecision(
        busy=True, has_live_session=False, quiet_for=LONG_QUIET_S
    ).should_idle


def test_hidden_session_stops_pinning_full_frame_rate() -> None:
    """A READY session whose element stopped painting must let the loop idle.

    The pool retains a session after its terminal element is hidden or
    removed; without the shown-recency gate a shell sitting at a prompt would
    hold the display at full frame rate forever.
    """
    session = RemoteSession("t1", "sh", lambda _frame: None)
    session._phase = RemotePhase.READY
    with patch("punt_lux.display.terminal.remote.time.monotonic", return_value=100.0):
        session.mark_shown()  # painted at t=100
    # A fraction of a second later it still counts; a full second later it does not.
    assert session.pins_frame_rate(100.1)
    assert not session.pins_frame_rate(101.0)


def test_recently_shown_but_not_yet_live_session_does_not_pin() -> None:
    """A CONNECTING session on screen must not pin: no output can arrive yet."""
    session = RemoteSession("t1", "sh", lambda _frame: None)  # phase CONNECTING
    with patch("punt_lux.display.terminal.remote.time.monotonic", return_value=100.0):
        session.mark_shown()
    assert not session.pins_frame_rate(100.1)


def test_hidden_session_lets_the_pool_idle() -> None:
    pool = RemotePool(Path("/nonexistent/luxd-pty.sock"))
    session = pool.get("t1", "sh")
    session._phase = RemotePhase.READY
    with patch("punt_lux.display.terminal.remote.time.monotonic", return_value=100.0):
        session.mark_shown()  # last painted at t=100
    with patch(
        "punt_lux.display.terminal.remote_pool.time.monotonic", return_value=101.0
    ):
        assert not pool._has_live_session
