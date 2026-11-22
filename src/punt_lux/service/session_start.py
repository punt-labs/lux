"""Safe SessionStart decisions shared by the installed hook entry points."""

from __future__ import annotations

import logging
from typing import final

from punt_lux.service.config import ConfigManager

logger = logging.getLogger(__name__)


@final
class SessionStartDecisions:
    """Record launch events and decide the display context without private data."""

    __slots__ = ()

    @staticmethod
    def _enabled() -> bool:
        try:
            return ConfigManager().read().display == "y"
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
