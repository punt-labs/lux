"""PortGuard -- verify a service's port is free or already ours, never foreign.

A legacy launchd label or systemd unit isn't the only way a stale process
can hold a service's port: a manually-started process with no plist or
unit at all can too. ``PortGuard`` is the second, independent check --
:class:`~punt_lux._legacy_sweep.LegacySweep` covers the labeled/unit case.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Literal, Self, final

from punt_lux._backends import pgrep_pid
from punt_lux._service_errors import PortConflictError
from punt_lux._service_spec import ServiceSpec

logger = logging.getLogger(__name__)

__all__ = ["PortGuard", "PortGuardResult"]


@final
@dataclass(frozen=True, slots=True)
class PortGuardResult:
    """The outcome of one port check: exactly one of these four states."""

    status: Literal["free", "ours", "foreign", "unknown"]
    pid: int | None  # the holding pid, when status is "foreign"; else None


@final
class PortGuard:
    """Verify the service's port is free or already ours; never both nor foreign."""

    __slots__ = ("_spec",)
    _spec: ServiceSpec

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        return self

    def check(self) -> PortGuardResult:
        """Non-mutating: who, if anyone, holds ``spec.health_port``.

        A service with no fixed port (``health_port is None``) reports
        ``"free"`` -- there is nothing to guard, the same no-op-on-absent-data
        posture :class:`~punt_lux._legacy_sweep.LegacySweep` takes for an
        empty identifier tuple.
        """
        port = self._spec.health_port
        if port is None:
            return PortGuardResult(status="free", pid=None)
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            logger.warning(
                "lsof not found on PATH; cannot verify port %d is free", port
            )
            return PortGuardResult(status="unknown", pid=None)
        pids = [int(line) for line in result.stdout.split() if line.strip()]
        if not pids:
            return PortGuardResult(status="free", pid=None)
        holder = pids[0]
        if holder == pgrep_pid(self._spec.process_name):
            return PortGuardResult(status="ours", pid=holder)
        return PortGuardResult(status="foreign", pid=holder)

    def guard(self) -> None:
        """Raise :class:`PortConflictError` unless ``check()`` confirms free-or-ours.

        Fail-closed: both ``"foreign"`` (a verified other process) and
        ``"unknown"`` (``lsof`` missing, so nothing was verified) raise.
        Proceeding on an unconfirmed assumption is exactly the silent
        pass-through this design exists to close out.
        """
        result = self.check()
        if result.status in ("free", "ours"):
            return
        port = self._spec.health_port
        if result.status == "foreign":
            msg = (
                f"port {port} is held by pid {result.pid}, not "
                f"{self._spec.process_name}. Inspect: "
                f"lsof -nP -iTCP:{port} -sTCP:LISTEN"
            )
        else:
            msg = f"cannot verify port {port} is free or ours -- lsof is not on PATH"
        raise PortConflictError(msg)
