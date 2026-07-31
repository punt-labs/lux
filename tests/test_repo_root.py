"""RepoRoot — finding the git repository a lux process runs inside.

One walk answers the question for every identity-declaring caller. These pin the
walk itself; the identity modules' own tests pin what each does with the answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from punt_lux.repo_root import RepoRoot

_NO_REPO = Path("/lux-headless-not-a-repo")


def test_finds_the_root_from_the_root_itself(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert RepoRoot.find(tmp_path) == tmp_path


def test_climbs_from_a_nested_directory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    assert RepoRoot.find(nested) == tmp_path


def test_a_worktree_git_file_counts(tmp_path: Path) -> None:
    """A worktree's or submodule's ``.git`` is a file, not a directory."""
    (tmp_path / ".git").write_text("gitdir: /elsewhere\n")
    assert RepoRoot.find(tmp_path) == tmp_path


def test_outside_a_repository_is_absence_not_an_error() -> None:
    assert RepoRoot.find(_NO_REPO) is None


def test_defaults_to_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    assert RepoRoot.find() == tmp_path
