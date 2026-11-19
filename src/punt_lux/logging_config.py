"""Configure Lux entry-point diagnostics through punt-observe."""

from __future__ import annotations

import logging
import traceback
from contextlib import contextmanager
from typing import TYPE_CHECKING, final

from punt_observe.logging import configure_logging as _configure_logging

from punt_lux.log_level import resolve_level

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


@final
class _Diagnostics:
    @staticmethod
    def configure(tool: str, role: str, *, verbose: bool = False) -> None:
        """Configure a private durable log with an optional diagnostic override."""
        level, invalid = ("DEBUG", False) if verbose else resolve_level("INFO")
        _configure_logging(
            tool,
            role,
            level=level,
            stderr_level="DEBUG" if verbose else "WARNING",
        )
        if invalid:
            logger.warning("Invalid LUX_LOG_LEVEL; using INFO")

    @staticmethod
    def failure_details(error: Exception) -> str:
        """Describe the exception type and stack locations without its message."""
        frames = " -> ".join(
            f"{frame.f_code.co_name}:{line}"
            for frame, line in traceback.walk_tb(error.__traceback__)
        )
        return f"{type(error).__name__} ({frames})"

    @classmethod
    @contextmanager
    def process(cls, role: str, name: str) -> Generator[None]:
        """Configure logging and record failures even when stderr is unavailable."""
        cls.configure("lux", role)
        try:
            yield
        except Exception as error:
            logger.error("%s failed: %s", name, cls.failure_details(error))
            raise


configure_logging = _Diagnostics.configure
failure_details = _Diagnostics.failure_details
process_diagnostics = _Diagnostics.process
