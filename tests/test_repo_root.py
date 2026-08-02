"""RepoRoot — the git repository a lux process runs inside, or the absence of one.

One walk answers the question for every identity-declaring caller, and the root
it returns answers what those callers actually need: what to call this context,
and what path to declare. These pin both, in both states; the identity modules'
own tests pin what each does with the answers.
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
    root = RepoRoot.of("headless", tmp_path)
    assert root.name == tmp_path.name
    assert root.declared_path == str(tmp_path)


def test_climbs_from_a_nested_directory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    assert RepoRoot.of("headless", nested).declared_path == str(tmp_path)


def test_a_worktree_git_file_counts(tmp_path: Path) -> None:
    """A worktree's or submodule's ``.git`` is a file, not a directory."""
    (tmp_path / ".git").write_text("gitdir: /elsewhere\n")
    assert RepoRoot.of("headless", tmp_path).declared_path == str(tmp_path)


def test_outside_a_repository_the_fallback_is_what_it_is_called() -> None:
    """The headless case is a state with an answer, not a hole for the caller."""
    assert RepoRoot.of("lux-cli", _NO_REPO).name == "lux-cli"


def test_outside_a_repository_nothing_is_declared() -> None:
    """A headless client owns no repository, which is what its identity declares."""
    assert RepoRoot.of("lux-cli", _NO_REPO).declared_path is None


def test_defaults_to_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    assert RepoRoot.of("headless").declared_path == str(tmp_path)
