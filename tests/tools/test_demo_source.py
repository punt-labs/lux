"""demo_source -- changed paths and the text they hold, from disk or from HEAD."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.tools.conftest import Repo
from tools.demo_source import ChangeSet, CommittedHead, GitError, WorkingTree


def test_change_set_lists_a_path_with_a_space(repo: Repo) -> None:
    (repo.path / "new file.txt").write_text("hi\n")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "add")
    assert ChangeSet(repo.path, "main").paths() == ["new file.txt"]


def test_change_set_lists_both_sides_of_a_rename(repo: Repo) -> None:
    repo.git("mv", "old name.txt", "new name.txt")
    repo.git("commit", "-q", "-m", "mv")
    assert sorted(ChangeSet(repo.path, "main").paths()) == [
        "new name.txt",
        "old name.txt",
    ]


def test_change_set_lists_a_deleted_file(repo: Repo) -> None:
    repo.git("rm", "-q", "gone.py")
    repo.git("commit", "-q", "-m", "rm")
    assert ChangeSet(repo.path, "main").paths() == ["gone.py"]


def test_change_set_omits_uncommitted_changes(repo: Repo) -> None:
    (repo.path / "keep.txt").write_text("edited\n")
    assert ChangeSet(repo.path, "main").paths() == []


def test_change_set_reports_git_stderr(repo: Repo) -> None:
    with pytest.raises(GitError, match="unknown-ref"):
        ChangeSet(repo.path, "unknown-ref").paths()


def test_working_tree_reads_the_file_on_disk(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    assert WorkingTree(tmp_path).read("a.py") == "x = 1\n"


def test_working_tree_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        WorkingTree(tmp_path).read("nope.py")


def test_committed_head_ignores_uncommitted_edits(repo: Repo) -> None:
    (repo.path / "keep.txt").write_text("edited\n")
    head = CommittedHead(ChangeSet(repo.path, "main"))
    assert head.read("keep.txt") == "keep\n"


def test_committed_head_raises_for_a_path_absent_from_head(repo: Repo) -> None:
    (repo.path / "untracked.py").write_text("x = 1\n")
    head = CommittedHead(ChangeSet(repo.path, "main"))
    with pytest.raises(FileNotFoundError):
        head.read("untracked.py")


def test_committed_head_reads_non_ascii_text(repo: Repo) -> None:
    (repo.path / "u.txt").write_text("caf\u00e9 \u2014\n", encoding="utf-8")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "u")
    head = CommittedHead(ChangeSet(repo.path, "main"))
    assert head.read("u.txt") == "caf\u00e9 \u2014\n"


@dataclass(frozen=True)
class Decoding:
    encoding: str
    errors: str


def test_git_output_is_decoded_as_utf8(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Decoding] = []

    def spy(
        args: Sequence[str],
        *,
        cwd: Path,
        capture_output: bool,
        encoding: str,
        errors: str,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        seen.append(Decoding(encoding, errors))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", spy)
    ChangeSet(repo.path, "HEAD").read_head("keep.txt")
    assert seen == [Decoding("utf-8", "strict")]
