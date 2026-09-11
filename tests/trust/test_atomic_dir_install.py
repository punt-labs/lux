"""Tests for AtomicDirInstall: create-into-tmp-then-atomic-rename."""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.trust.atomic_dir_install import AtomicDirInstall


def test_finish_calls_on_win_and_installs_the_staging_dir(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    install = AtomicDirInstall(dest)
    (install.staging_dir).mkdir(parents=True)
    (install.staging_dir / "marker").write_text("hello")

    result = install.finish(lambda: "won", lambda: "lost")

    assert result == "won"
    assert dest.is_dir()
    assert (dest / "marker").read_text() == "hello"
    assert not install.staging_dir.exists()


def test_finish_calls_on_lose_and_discards_the_staging_dir_on_conflict(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "winner-marker").write_text("winner")

    install = AtomicDirInstall(dest)
    install.staging_dir.mkdir(parents=True)
    (install.staging_dir / "loser-marker").write_text("loser")

    result = install.finish(lambda: "won", lambda: "lost")

    assert result == "lost"
    # The winner's content is untouched; the loser's staging is gone.
    assert (dest / "winner-marker").read_text() == "winner"
    assert not (dest / "loser-marker").exists()
    assert not install.staging_dir.exists()


def test_staging_dir_is_a_sibling_of_the_destination(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    install = AtomicDirInstall(dest)
    assert install.staging_dir.parent == dest.parent
    assert install.staging_dir != dest


def test_finish_reraises_a_non_race_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine I/O failure (permission, ENOSPC, cross-device rename) must
    surface as itself, not get misclassified as a race loss — the
    destination was never populated, so there is no winner to defer to.
    """
    dest = tmp_path / "dest"
    install = AtomicDirInstall(dest)
    install.staging_dir.mkdir(parents=True)

    def _permission_denied(_self: Path, _target: str | Path) -> Path:
        msg = "Permission denied"
        raise PermissionError(msg)

    monkeypatch.setattr(Path, "rename", _permission_denied)

    with pytest.raises(PermissionError):
        install.finish(lambda: "won", lambda: "lost")

    # Not treated as a race loss: the staged content is left in place, not
    # discarded, because this was never a real race to lose.
    assert install.staging_dir.exists()
    assert not dest.exists()


def test_discard_removes_the_staging_dir(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    install = AtomicDirInstall(dest)
    install.staging_dir.mkdir(parents=True)
    (install.staging_dir / "secret").write_text("private-key-bytes")

    install.discard()

    assert not install.staging_dir.exists()


def test_discard_is_a_noop_when_staging_never_existed(tmp_path: Path) -> None:
    install = AtomicDirInstall(tmp_path / "dest")
    install.discard()  # must not raise
    assert not install.staging_dir.exists()


def test_build_populates_the_staging_dir(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    install = AtomicDirInstall(dest)

    def _populate(staging: Path) -> None:
        staging.mkdir(parents=True)
        (staging / "f").write_text("x")

    install.build(_populate)

    assert (install.staging_dir / "f").read_text() == "x"


def test_build_discards_the_staging_dir_on_failure(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    install = AtomicDirInstall(dest)

    def _populate(staging: Path) -> None:
        staging.mkdir(parents=True)
        (staging / "partial-key").write_text("half-written")
        msg = "disk full"
        raise OSError(msg)

    with pytest.raises(OSError, match="disk full"):
        install.build(_populate)

    assert not install.staging_dir.exists()
