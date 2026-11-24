"""Where the demo gate reads a PR's changed paths and their text from."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, Self


class GitError(RuntimeError):
    """A git command the change set needs failed."""


class ChangeSet:
    """The paths a branch changes relative to a base ref."""

    _root: Path
    _base_ref: str

    def __new__(cls, root: Path, base_ref: str) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._base_ref = base_ref
        return self

    def paths(self) -> list[str]:
        """Return paths changed between the merge base with the base ref and HEAD.

        Covers committed changes only, so the verdict is for the head the demo
        comment names. Omits uncommitted and untracked files. A rename lists
        both its old and new path; a deletion lists the deleted path.
        """
        base = self._git("merge-base", self._base_ref, "HEAD").strip()
        diff = self._git("diff", "--name-only", "-z", "--no-renames", base, "HEAD")
        return [path for path in diff.split("\0") if path]

    def read_head(self, path: str) -> str:
        """Return the file as committed at HEAD; FileNotFoundError if absent there."""
        try:
            return self._git("show", f"HEAD:{path}")
        except GitError as error:
            if "in 'HEAD'" in str(error):
                raise FileNotFoundError(path) from error
            raise

    def _git(self, *args: str) -> str:
        done = subprocess.run(
            ["git", *args],
            cwd=self._root,
            capture_output=True,
            encoding="utf-8",
            errors="strict",
            check=False,
        )
        if done.returncode:
            raise GitError(f"git {' '.join(args)}: {done.stderr.strip()}")
        return done.stdout


class Source(Protocol):
    """Where a changed file's text comes from."""

    def read(self, path: str) -> str:
        """Return the file's text; FileNotFoundError when it does not exist."""
        ...


class WorkingTree:
    """Files as they are on disk."""

    _root: Path

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    def read(self, path: str) -> str:
        return (self._root / path).read_text(encoding="utf-8")


class CommittedHead:
    """Files as committed at HEAD, so the verdict is for the head the demo names."""

    _changes: ChangeSet

    def __new__(cls, changes: ChangeSet) -> Self:
        self = super().__new__(cls)
        self._changes = changes
        return self

    def read(self, path: str) -> str:
        return self._changes.read_head(path)
