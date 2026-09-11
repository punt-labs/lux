"""_RenameOutcome — classify a failed directory rename as a race loss or a
genuine I/O failure, cleaning up after a race loss and re-raising anything
else so a real error is never mistaken for "someone else won."
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import final

__all__ = ["_RenameOutcome"]


@final
class _RenameOutcome:
    """Namespace for classifying one atomic-rename attempt."""

    @staticmethod
    def commit(staging: Path, dest: Path) -> bool:
        """Rename *staging* onto *dest*; return whether this attempt won.

        Raises whatever ``OSError`` the rename failed with unless *dest*
        already exists — the one failure mode a race loss produces
        (another writer's rename got there first). *staging* is discarded
        only in that case; any other failure leaves it in place.
        """
        try:
            staging.rename(dest)
        except OSError:
            if not dest.exists():
                raise
            shutil.rmtree(staging)
            return False
        return True
