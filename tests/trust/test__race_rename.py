"""Tests for _RenameOutcome: classify a failed rename as race-loss or not."""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.trust._race_rename import _RenameOutcome


def test_commit_returns_true_when_the_rename_succeeds(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    dest = tmp_path / "dest"

    assert _RenameOutcome.commit(staging, dest) is True
    assert dest.is_dir()
    assert not staging.exists()


def test_commit_returns_false_and_cleans_up_on_a_race_loss(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "winner-marker").write_text("winner")

    assert _RenameOutcome.commit(staging, dest) is False
    assert (dest / "winner-marker").read_text() == "winner"
    assert not staging.exists()


def test_commit_reraises_a_non_race_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    dest = tmp_path / "dest"

    def _permission_denied(_self: Path, _target: str | Path) -> Path:
        msg = "Permission denied"
        raise PermissionError(msg)

    monkeypatch.setattr(Path, "rename", _permission_denied)

    with pytest.raises(PermissionError):
        _RenameOutcome.commit(staging, dest)

    # Not a race loss: staging is left in place, not discarded.
    assert staging.exists()
    assert not dest.exists()
