"""Install a beads board through the operations facade, surfacing rejections."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, final

from punt_lux.operations import OpError, RenderTableRequest
from punt_lux.tools import tools as _core

if TYPE_CHECKING:
    from punt_lux.apps.beads_board import BeadsBoard
    from punt_lux.operations import RenderRequest, Scope

# ``_core.OPERATIONS`` is read at call time, never imported by value: tests
# rebind ``punt_lux.tools.tools.OPERATIONS`` to an isolated store, and a
# value-import would freeze the production facade past that rebind. This module
# is imported lazily (by ``BeadsBrowser.render``), so it sits outside the
# tools -> clients -> beads load cycle and imports ``tools`` at the top.

_log = logging.getLogger(__name__)


@final
class BeadsBoardInstaller:
    """Install a beads board Hub-side, reporting a rejection instead of dropping it.

    The Hub operations return a rejection as an ``OpError`` value, not an
    exception, and the menu's background-thread wrapper catches only exceptions —
    so a discarded return means a rejected board vanishes with no scene, no error,
    no log. This installer logs the reason and shows a red failure scene, matching
    the CLI surface rather than failing silently.
    """

    __slots__ = ()

    @classmethod
    def install(
        cls,
        board: BeadsBoard,
        request: RenderTableRequest | RenderRequest,
        scope: Scope,
    ) -> None:
        """Render the board request; on a rejection, report it visibly."""
        result = (
            _core.OPERATIONS.render_table(request, scope=scope)
            if isinstance(request, RenderTableRequest)
            else _core.OPERATIONS.render(request, scope=scope)
        )
        if isinstance(result, OpError):
            cls._report(board, scope, result.reason)

    @staticmethod
    def _report(board: BeadsBoard, scope: Scope, reason: str) -> None:
        """Log a rejected board and install a visible red failure scene.

        If the failure scene is itself rejected, log that too — never give up
        silently.
        """
        _log.error("beads board rejected: %s", reason)
        message = board.failure(f"Beads board could not be shown — {reason}")
        if isinstance(_core.OPERATIONS.render(message, scope=scope), OpError):
            _log.error("beads board failure scene also rejected")
