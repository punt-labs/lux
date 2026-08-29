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
    pid: int | None  # the holding pid, when status is "ours" or "foreign"; else None
    reason: str | None = None  # human-readable why, set only when status is "unknown"


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
            return PortGuardResult(
                status="unknown", pid=None, reason="lsof is not on PATH"
            )
        if result.returncode > 1:
            # lsof exits 1 for "no matches" (normal); anything higher is a
            # real failure (bad args, permission) -- fail closed, not free.
            logger.warning(
                "lsof exited %d checking port %d; cannot verify free or ours",
                result.returncode,
                port,
            )
            return PortGuardResult(
                status="unknown",
                pid=None,
                reason=(
                    f"lsof exited {result.returncode} (real failure, not a no-match)"
                ),
            )
        pids = [int(line) for line in result.stdout.split() if line.strip()]
        if not pids:
            return PortGuardResult(status="free", pid=None)
        ours = pgrep_pid(self._spec.process_name)
        # lsof -t can list multiple pids (SO_REUSEPORT, multiple listeners);
        # any pid that isn't ours means the port isn't exclusively ours.
        foreign = next((pid for pid in pids if pid != ours), None)
        if foreign is not None:
            return PortGuardResult(status="foreign", pid=foreign)
        return PortGuardResult(status="ours", pid=ours)

    def guard(self) -> None:
        """Raise :class:`PortConflictError` unless ``check()`` confirms free-or-ours.

        Fail-closed: both ``"foreign"`` (a verified other process) and
        ``"unknown"`` (verification failed for any reason — ``lsof`` missing
        from PATH, or ``lsof`` exited with a non-normal code) raise.
        The specific reason for ``"unknown"`` is carried in
        ``PortGuardResult.reason`` and included in the raised error message,
        so a permissions failure isn't misdiagnosed as a missing binary.
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
            reason = result.reason or "unknown reason"
            msg = f"cannot verify port {port} is free or ours -- {reason}"
        raise PortConflictError(msg)
