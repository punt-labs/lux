"""Pending observations and replacement dials restart the complete interval."""

from __future__ import annotations

from punt_lux.service._display_stability import DisplayStability


def test_initial_and_reset_phases_do_not_claim_connectivity() -> None:
    window = DisplayStability(3)
    assert not bool(window.started)
    assert "before" in window.phase(0)
    assert not window.observe(None, 0)
    assert not window.observe("first", 0)
    assert bool(window.started)
    assert "2.0s" in window.phase(2)
    assert not window.observe("second", 3)
    assert not window.observe("second", 5.9)
    assert window.observe("second", 6)
    assert not window.observe(None, 7)
    assert not bool(window.started)
