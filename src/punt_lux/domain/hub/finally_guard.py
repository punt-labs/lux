"""FinallyGuard -- an action in a ``finally`` that may not hide the failure it follows.

A settle or a release runs in a ``finally`` so that it happens whatever the body did.
When the body raised and the action raises too, Python lets the second replace the
first, and the read failure that caused everything disappears from the traces. The
guard runs the action; if a failure is already in flight it logs the action's own
failure, with its chain, and lets the original go on.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = ["FinallyGuard"]


@final
class FinallyGuard:
    """Runs the action of a ``finally`` block."""

    __slots__ = ()

    @staticmethod
    def run(action: Callable[[], object], what: str) -> None:
        """Run ``action``; its failure never replaces one already being raised.

        With nothing in flight the action's failure propagates as any would. With a
        failure in flight it is logged as ``what`` failing, chained to the original,
        and the original is the one that goes on.
        """
        original = sys.exception()
        if original is None:
            action()
            return
        try:
            action()
        except Exception:
            logger.exception("%s failed while handling %r", what, original)
