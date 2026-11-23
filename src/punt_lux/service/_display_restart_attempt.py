"""The initial facts captured before one supervised Display restart."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.service import ServiceActionFailedError, _backends
from punt_lux.service._restart_readiness import RestartReadiness

if TYPE_CHECKING:
    from punt_lux.service import ServiceSpec


class ReadinessError(RuntimeError):
    """A Display never became ready or lost its observed generation."""


@dataclass(frozen=True, slots=True)
class RestartAttempt:
    """Configuration and pre-restart process identity for one attempt."""

    spec: ServiceSpec
    before: int | None
    started_at: float
    wait: float

    @classmethod
    def capture(cls, spec: ServiceSpec, wait: float) -> Self:
        """Capture the timestamp before the initial, bounded process lookup."""
        started_at = time.time()
        try:
            before = _backends.pgrep_pid(spec.process_name)
        except subprocess.TimeoutExpired as error:
            message = f"cannot inspect Display before restart: {error}"
            RestartReadiness.failure(spec, message)
            raise ServiceActionFailedError(message) from error
        return cls(spec=spec, started_at=started_at, before=before, wait=wait)
