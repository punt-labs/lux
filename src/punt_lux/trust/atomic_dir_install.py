"""AtomicDirInstall — build into a sibling dir, install with one atomic rename."""

from __future__ import annotations

import shutil
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
        self._dest, self._staging = dest, dest.parent / f".{dest.name}.tmp{uuid4().hex}"
        return self

    @property
    def staging_dir(self) -> Path:
        """Return the sibling temp dir to build the new content into."""
        return self._staging

    def discard(self) -> None:
        """Remove the staging dir; best-effort (cleanup never masks a real error)."""
        shutil.rmtree(self._staging, ignore_errors=True)

    def build(self, populate: Callable[[Path], None]) -> None:
        """Call ``populate(staging_dir)``, discarding it on ``OSError``."""
        try:
            populate(self._staging)
        except OSError:
            self.discard()
            raise

    def finish(self, on_win: Callable[[], _T], on_lose: Callable[[], _T]) -> _T:
        """Commit the staging dir; *on_win* if this rename won, else *on_lose*."""
        won = _RenameOutcome.commit(self._staging, self._dest)
        return on_win() if won else on_lose()
