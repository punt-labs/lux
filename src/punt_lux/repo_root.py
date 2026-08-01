"""RepoRoot — the git repository a lux process is running inside.

Every client that declares an identity to the Hub names the repository it works
in, and that repository is read from the filesystem rather than configured: the
directory the process started in, or the first ancestor of it holding a ``.git``
entry. One class answers that question for every caller — a ``lux`` command
(:class:`~punt_lux.cli_identity.CliIdentity`) and a session's MCP server
(:class:`~punt_lux.session_identity.AppletIdentity`) — so the two cannot drift
onto different derivations of the same fact.

Not being in a repository is a real state rather than a failure, and this class
owns what callers do about it. :meth:`RepoRoot.of` takes the name to use when
there is no repository and answers ``name`` and ``declared_path`` for both cases,
so a caller reads the two values it needs instead of testing for absence twice
and deriving each itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self, final

__all__ = ["RepoRoot"]


@final
class RepoRoot:
    """The repository a process runs in, or the named absence of one."""

    # A found root's directory. Absent is the headless case — the process runs
    # outside any repository — which the accessors answer for, so no caller of
    # this class ever sees the None.
    _path: Path | None
    _headless_name: str
    __slots__ = ("_headless_name", "_path")

    def __new__(cls, path: Path | None, headless_name: str) -> Self:
        self = super().__new__(cls)
        self._path = path
        self._headless_name = headless_name
        return self

    @classmethod
    def of(cls, headless_name: str, start: Path | None = None) -> Self:
        """Find the repository at or above ``start`` (default cwd).

        Walk the directory and its parents for a ``.git`` entry — a directory in
        a normal clone, a file in a worktree or submodule, so ``exists`` catches
        both. The walk falling through is the headless case, not an error, and no
        subprocess is spawned to answer a question the filesystem already holds.
        """
        origin = start or Path.cwd()
        for directory in (origin, *origin.parents):
            if (directory / ".git").exists():
                return cls(directory, headless_name)
        return cls(None, headless_name)

    @property
    def name(self) -> str:
        """What to call this context: the directory's name, or the fallback."""
        return self._path.name if self._path is not None else self._headless_name

    @property
    def declared_path(self) -> str | None:
        """The absolute path an identity declares, or ``None`` when headless.

        ``None`` here is the declaration itself — a headless client owns no
        repository, which is exactly what ``ClientIdentity.repo`` expects of one —
        so callers pass this straight through rather than re-deriving it.
        """
        return str(self._path) if self._path is not None else None
