"""Shared fixtures for the tools tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


class Repo:
    """A throwaway git repository on a feature branch off main."""

    _path: Path

    def __new__(cls, path: Path) -> Repo:
        self = super().__new__(cls)
        self._path = path
        return self

    @property
    def path(self) -> Path:
        return self._path

    def git(self, *args: str) -> None:
        subprocess.run(
            [
                shutil.which("git") or "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.com",
                *args,
            ],
            cwd=self._path,
            check=True,
            capture_output=True,
        )


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    made = Repo(tmp_path)
    made.git("init", "-q", "-b", "main")
    (tmp_path / "keep.txt").write_text("keep\n")
    (tmp_path / "old name.txt").write_text("rename me\n")
    (tmp_path / "gone.py").write_text("x = 1\n")
    made.git("add", ".")
    made.git("commit", "-q", "-m", "base")
    made.git("checkout", "-q", "-b", "feature")
    return made
