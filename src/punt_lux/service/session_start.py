"""Safe SessionStart decisions shared by the installed hook entry points."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import final

from punt_lux.service.config import (
    DEFAULT_CONFIG_PATH,
    ConfigManager,
    resolve_config_path,
)
from punt_lux.service.repo_activation import Checkout

logger = logging.getLogger(__name__)


@final
class SessionStartDecisions:
    """Record launch events and decide the display context without private data."""

    __slots__ = ()

    @staticmethod
    def _enabled() -> bool:
        try:
            path = resolve_config_path()
            main = path.parents[len(DEFAULT_CONFIG_PATH.parts) - 1]
            checkout = Checkout.find(Path.cwd())
            root = main if checkout is None else checkout.root
            return ConfigManager.for_display(root, main=main).read().display == "y"
        except Exception as error:
            logger.error(
                "SessionStart display decision failed: %s", type(error).__name__
            )
            raise

    @classmethod
    def display_context(cls, enabled_context: str) -> str:
        """Read display mode and log a safe decision even if configuration fails."""
        enabled = cls._enabled()
        logger.info(
            "SessionStart display decision: %s", "enabled" if enabled else "disabled"
        )
        return (
            enabled_context
            if enabled
            else "Lux display mode: off. Visual output disabled."
        )
