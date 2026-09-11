"""AtomicDirInstall — build into a sibling temp directory, then install it
with one atomic ``os.rename``, so two racing writers can never leave a
destination holding a torn mix of each other's files.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Self, TypeVar, final
from uuid import uuid4

from punt_lux.trust._race_rename import _RenameOutcome

__all__ = ["AtomicDirInstall"]

_T = TypeVar("_T")


@final
class AtomicDirInstall:
    """A staging directory that installs itself atomically, or not at all."""

    _dest: Path
    _staging: Path
    __slots__ = ("_dest", "_staging")

    def __new__(cls, dest: Path) -> Self:
        self = super().__new__(cls)
        self._dest = dest
        self._staging = dest.parent / f".{dest.name}.tmp-{uuid4().hex}"
        return self

    @property
    def staging_dir(self) -> Path:
        """Return the sibling temp directory to build the new content into."""
        return self._staging

    def finish(self, on_win: Callable[[], _T], on_lose: Callable[[], _T]) -> _T:
        """Commit the staged directory onto the destination.

        Calls *on_win* if this install's rename got there first, or
        *on_lose* if another writer's rename beat it to *self._dest*.
        Anything other than that specific race loss — permission,
        ENOSPC, a cross-device rename — is not misclassified as one; see
        :class:`_RenameOutcome`.
        """
        if _RenameOutcome.commit(self._staging, self._dest):
            return on_win()
        return on_lose()
