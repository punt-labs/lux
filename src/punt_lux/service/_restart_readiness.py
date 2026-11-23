"""Bound restart readiness polling and capture supervisor failure diagnostics."""

from __future__ import annotations

import logging
import platform
import subprocess
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from punt_lux.service._backend_launchd import LaunchdBackend

if TYPE_CHECKING:
    from punt_lux.service import ServiceSpec

logger = logging.getLogger(__name__)


class RestartReadiness:
    """Own bounded readiness delays and best-effort failure observations."""

    @staticmethod
    def polls(wait_seconds: float, poll_seconds: float) -> Iterator[None]:
        """Yield the bounded sequence of restart poll delays."""
        for _ in range(int(wait_seconds / poll_seconds)):
            time.sleep(poll_seconds)
            yield

    @classmethod
    def failure(cls, spec: ServiceSpec, message: str) -> None:
        """Log a readiness failure with a bounded, non-mutating launchd probe."""
        logger.error(
            "%s readiness failed: %s; %s",
            spec.launchd_label,
            message,
            cls._status(spec),
        )

    @staticmethod
    def _status(spec: ServiceSpec) -> str:
        if platform.system() != "Darwin":
            return "launchd state unavailable on this platform"
        try:
            return LaunchdBackend(spec).registration_status()
        except subprocess.TimeoutExpired as error:
            return f"launchctl print: timed out after {error.timeout}s"
        except OSError as error:
            return f"launchctl print: unavailable ({type(error).__name__})"
