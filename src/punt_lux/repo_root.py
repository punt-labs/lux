"""RepoRoot — the git repository a lux process is running inside.

Every client that declares an identity to the Hub names the repository it works
in, and that repository is read from the filesystem rather than configured: the
directory the process started in, or the first ancestor of it holding a ``.git``
entry. One class answers that question for every caller — a ``lux`` command
(:class:`~punt_lux.cli_identity.CliIdentity`) and a session's MCP server
(:class:`~punt_lux.session_identity.SessionIdentity`) — so the two cannot drift
onto different derivations of the same fact.
"""

from __future__ import annotations

from pathlib import Path
from typing import final

__all__ = ["RepoRoot"]


@final
class RepoRoot:
    """The git repository above a working directory, when there is one."""

    __slots__ = ()

    @staticmethod
    def find(start: Path | None = None) -> Path | None:
        """Return the git root at or above ``start`` (default cwd), or ``None``.

        Walk the directory and its parents for a ``.git`` entry — a directory in a
        normal clone, a file in a worktree or submodule, so ``exists`` catches
        both. Not being in a repository is the documented headless case (a client
        that owns no repo), so the walk falling through returns ``None`` rather
        than raising, and no subprocess is spawned to answer a question the
        filesystem already holds.
        """
        origin = start or Path.cwd()
        for directory in (origin, *origin.parents):
            if (directory / ".git").exists():
                return directory
        return None
