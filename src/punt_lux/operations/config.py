"""DisplayModeOperations — read a project's display-mode config; the file's
path and I/O belong to DisplayModeStore, so a read failure surfaces as a fault.

Writing moved out of the Hub entirely (DES-088): a user path to per-repo
enable/disable is the enablement/install flow's committed marker, not a
client setter routed through the Hub -- see ``cli/display.py``'s ``mode()``
SET branch, which now writes ``DisplayModeStore`` directly.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.operations.display_mode_store import DisplayModeStore
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.config import DisplayModeRequest, DisplayModeState

__all__ = ["DisplayModeOperations"]


@final
class DisplayModeOperations:
    """Read the per-project display mode."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def read_display_mode(self, repo: str) -> DisplayModeState | OpError:
        """Return the mode ``<repo>/.punt-labs/lux.md`` records, or an ``OpError``."""
        repo_error = DisplayModeRequest.check_repo(repo)
        if repo_error is not None:
            return repo_error
        return DisplayModeStore(repo).read()
