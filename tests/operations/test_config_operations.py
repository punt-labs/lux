"""DisplayModeOperations read against a temp repo.

Writing moved out of the Hub entirely (DES-088): the CLI writes
``DisplayModeStore`` directly (``cli/display.py``'s ``mode()`` SET branch),
so there is no ``DisplayModeOperations.write_display_mode`` left to test here
-- ``DisplayModeStore`` itself covers the write, and its own test module
(``tests/operations/test_display_mode_store.py``) is the reference for that.
"""

from __future__ import annotations

from pathlib import Path

from punt_lux.operations import DisplayModeState, OpError
from punt_lux.operations.config import DisplayModeOperations
from punt_lux.operations.display_mode_store import DisplayModeStore


def _ops() -> DisplayModeOperations:
    return DisplayModeOperations()


def test_read_reflects_a_prior_write(tmp_path: Path) -> None:
    fault = DisplayModeStore(str(tmp_path)).write("y")
    assert fault is None
    state = _ops().read_display_mode(str(tmp_path))
    assert isinstance(state, DisplayModeState)
    assert state.mode == "on"


def test_read_rejects_a_relative_repo_without_raising() -> None:
    result = _ops().read_display_mode("relative/path")
    assert isinstance(result, OpError)
    assert "absolute path" in result.reason


def test_read_rejects_a_missing_repo_without_raising(tmp_path: Path) -> None:
    result = _ops().read_display_mode(str(tmp_path / "nope"))
    assert isinstance(result, OpError)
    assert "does not exist" in result.reason
