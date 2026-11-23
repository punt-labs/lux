"""Recover a missing launchd registration without replacing loaded jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from subprocess import CompletedProcess

    from punt_lux.service._launchd_plist import LaunchdPlist

logger = logging.getLogger(__name__)


class LaunchdRestart:
    """Interpret kickstart's status and bootstrap only a missing installed job."""

    __slots__ = ("_bootstrap", "_plist")
    _plist: LaunchdPlist
    _bootstrap: Callable[[], bool]

    def __new__(cls, plist: LaunchdPlist, bootstrap: Callable[[], bool]) -> Self:
        self = super().__new__(cls)
        self._plist = plist
        self._bootstrap = bootstrap
        return self

    def finish(self, result: CompletedProcess[str]) -> bool:
        """Report kickstart failure, recovering only rc=113 with a retained plist."""
        if result.returncode == 0:
            return True
        label = self._plist.spec.launchd_label
        logger.warning(
            "launchctl kickstart failed (rc=%d) for %s: %s",
            result.returncode,
            label,
            result.stderr.strip(),
        )
        if result.returncode == 113 and self._plist.path.exists():
            logger.warning(
                "%s is not registered; bootstrapping installed plist %s",
                label,
                self._plist.path,
            )
            return self._bootstrap()
        return False
