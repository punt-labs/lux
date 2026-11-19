"""Configure Lux entry-point diagnostics through punt-observe."""

from __future__ import annotations

import logging
import traceback
from contextlib import contextmanager
from typing import TYPE_CHECKING

from punt_observe.logging import configure_logging as _configure_logging

from punt_lux.log_level import resolve_level

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


def configure_logging(tool: str, role: str, *, verbose: bool = False) -> None:
    """Configure a private durable log with an optional diagnostic override."""
    default = "DEBUG" if verbose else "INFO"
    level, invalid = resolve_level(default)
    _configure_logging(
        tool,
        role,
        level=level,
        stderr_level="DEBUG" if verbose else "WARNING",
    )
    if invalid:
        logger.warning("Invalid LUX_LOG_LEVEL; using %s", default)


def failure_details(error: Exception) -> str:
    """Describe the exception type and stack locations without its message."""
    frames = " -> ".join(
        f"{frame.f_code.co_name}:{line}"
        for frame, line in traceback.walk_tb(error.__traceback__)
    )
    return f"{type(error).__name__} ({frames})"


@contextmanager
def process_diagnostics(role: str, process: str) -> Generator[None]:
    """Configure logging and record failures even when stderr is unavailable."""
    configure_logging("lux", role)
    try:
        yield
    except Exception as error:
        logger.error("%s failed: %s", process, failure_details(error))
        raise
