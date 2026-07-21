"""DisplayModeOperations read/write against a temp repo and a fake registry."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from punt_lux.domain.hub.clients import ClientRegistry
from punt_lux.operations import DisplayModeRequest
from punt_lux.operations.config import DisplayModeOperations


class _FakeRegistry:
    """Records eager-connect calls without touching a socket."""

    def __init__(self) -> None:
        self.gets = 0

    def get(self) -> object:
        self.gets += 1
        return object()


def _ops(registry: _FakeRegistry) -> DisplayModeOperations:
    return DisplayModeOperations(cast("ClientRegistry", registry))


def test_write_on_persists_y_and_eagerly_connects(tmp_path: Path) -> None:
    registry = _FakeRegistry()
    state = _ops(registry).write_display_mode(
        DisplayModeRequest(mode="on", repo=str(tmp_path))
    )
    assert state.mode == "on"
    assert 'display: "y"' in (tmp_path / ".punt-labs" / "lux.md").read_text()
    assert registry.gets == 1


def test_write_off_persists_n_without_connecting(tmp_path: Path) -> None:
    registry = _FakeRegistry()
    state = _ops(registry).write_display_mode(
        DisplayModeRequest(mode="off", repo=str(tmp_path))
    )
    assert state.mode == "off"
    assert 'display: "n"' in (tmp_path / ".punt-labs" / "lux.md").read_text()
    assert registry.gets == 0


def test_read_reflects_a_prior_write(tmp_path: Path) -> None:
    ops = _ops(_FakeRegistry())
    ops.write_display_mode(DisplayModeRequest(mode="on", repo=str(tmp_path)))
    assert ops.read_display_mode(str(tmp_path)).mode == "on"


def test_read_rejects_a_relative_repo() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        _ops(_FakeRegistry()).read_display_mode("relative/path")


def test_read_rejects_a_missing_repo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        _ops(_FakeRegistry()).read_display_mode(str(tmp_path / "nope"))
