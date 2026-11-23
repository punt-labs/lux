"""Install launchd configuration with explicit migration failure diagnostics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Self

from punt_lux.service._legacy_sweep_launchd import LaunchdLegacySweep
from punt_lux.service._service_errors import ServiceMigrationError

if TYPE_CHECKING:
    from punt_lux.service._launchd_plist import LaunchdPlist

logger = logging.getLogger(__name__)


class LaunchdInstallation:
    """Coordinate plist replacement and report failed bootstrap without retries."""

    __slots__ = ("_bootstrap", "_plist")
    _plist: LaunchdPlist
    _bootstrap: Callable[[], bool]

    def __new__(cls, plist: LaunchdPlist, bootstrap: Callable[[], bool]) -> Self:
        self = super().__new__(cls)
        self._plist = plist
        self._bootstrap = bootstrap
        return self

    def run(self, content: str, *, active: bool) -> bool:
        """Replace changed configuration, returning whether installation was a no-op."""
        label = self._plist.spec.launchd_label
        if active:
            if self._plist.installed_content() == content:
                logger.info("%s already installed and up to date; no-op", label)
                return True
            LaunchdLegacySweep(
                replace(self._plist.spec, legacy_launchd_labels=(label,))
            ).sweep()
            logger.info("Deregistered existing %s before upgrade", label)
        self._plist.write(content)
        logger.info("Wrote %s", self._plist.path)
        if not self._bootstrap():
            logger.error(
                "Failed to bootstrap %s from %s; leaving configuration in place; "
                "launchd registration is not guaranteed",
                label,
                self._plist.path,
            )
            msg = f"failed to bootstrap {label} into launchd"
            raise ServiceMigrationError(msg)
        logger.info("Bootstrapped %s into launchd", label)
        return False
