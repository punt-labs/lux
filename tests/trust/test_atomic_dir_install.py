"""Tests for AtomicDirInstall: create-into-tmp-then-atomic-rename."""

from __future__ import annotations

from pathlib import Path

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
