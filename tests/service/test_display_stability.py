"""Pending observations and replacement dials restart the complete interval."""

from __future__ import annotations

from punt_lux.service._display_stability import DisplayStability


def test_initial_and_reset_phases_do_not_claim_connectivity() -> None:
    window = DisplayStability(3)
    assert not bool(window.started)
    assert "before" in window.phase(0)
    assert not window.observe(None, (0, 0))
    assert not window.observe("first", (0, 0))
    assert bool(window.started)
    assert "2.0s" in window.phase(2)
    assert not window.observe("second", (3, 3))
    assert not window.observe("second", (5.9, 5.9))
    assert window.observe("second", (6, 6))
    assert not window.observe(None, (7, 7))
    assert not bool(window.started)


def test_only_time_between_first_receipt_and_latest_send_is_credited() -> None:
    window = DisplayStability(3)
    assert not window.observe("dial", (0, 0.4))
    assert not window.observe("dial", (3, 3.5))
    assert window.observe("dial", (3.4, 3.8))


def test_a_zero_length_window_still_requires_a_reply() -> None:
    window = DisplayStability(0)
    assert not window.observe(None, (0, 0.1))
    assert window.observe("dial", (0.2, 0.3))


def test_a_preexisting_dial_still_needs_a_full_observation_window() -> None:
    window = DisplayStability(3)
    assert not window.observe("preexisting", (99.5, 100))
    assert not window.observe("preexisting", (102.99, 103.1))
    assert window.observe("preexisting", (103, 103.2))
