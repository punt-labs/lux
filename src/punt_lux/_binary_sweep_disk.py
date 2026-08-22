"""DiskBinaryLegacySweep -- cure stale ``uv tool install`` shims in ``~/.local/bin``.

No platform split: unlike launchd/systemd, ``uv tool install``'s shim layout
(``~/.local/bin/<name>`` -> ``<uv tool dir>/<package>/bin/<name>``) is uv's own
behavior on both macOS and Linux, so this is the one and only implementation --
composed directly by :class:`~punt_lux.service.ServiceManager`, never routed
through :func:`~punt_lux._platform_dispatch.platform_classes`
(``docs/architecture/binary-rename-migration.md`` §2.2).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Self, final

from punt_lux._binary_sweep import BinarySweepReport, DiskBinaryOutcome
from punt_lux._service_errors import ServiceMigrationError
from punt_lux._service_spec import ServiceSpec
from punt_lux._shim_ownership import ShimOwnership

logger = logging.getLogger(__name__)

__all__ = ["DiskBinaryLegacySweep"]

# uv's own tool-install directory layout is package-scoped: <uv tool dir>/<pkg>/bin/.
_UV_TOOL_PACKAGE = "punt-lux"


@final
class DiskBinaryLegacySweep:
    """Remove uv-tool shims left behind by a ``[project.scripts]`` rename."""

    __slots__ = ("_bin_dir", "_ownership", "_spec")
    _bin_dir: Path
    _spec: ServiceSpec
    _ownership: ShimOwnership

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._bin_dir = Path.home() / ".local" / "bin"
        self._ownership = ShimOwnership(_UV_TOOL_PACKAGE)
        return self

    def is_clean(self) -> bool:
        """Return whether every legacy binary is already clean, without mutating."""
        return self.diagnose().all_clean

    def diagnose(self) -> BinarySweepReport:
        """Non-mutating: build a report of every legacy binary's current state."""
        outcomes = tuple(
            self._diagnose_one(name) for name in self._spec.legacy_binary_names
        )
        return BinarySweepReport(outcomes=outcomes)

    def sweep(self) -> BinarySweepReport:
        """Cure every legacy binary; raise once with the full report if any fails.

        A refusal (ownership could not be verified) is fatal, exactly like an
        outright removal failure -- this codebase never deletes a file it
        cannot confirm is its own shim (§6).
        """
        outcomes = tuple(
            self._sweep_one(name) for name in self._spec.legacy_binary_names
        )
        report = BinarySweepReport(outcomes=outcomes)
        if not report.all_clean:
            msg = f"legacy disk-binary cleanup failed:\n{report.describe()}"
            raise ServiceMigrationError(msg)
        return report

    def _diagnose_one(self, name: str) -> DiskBinaryOutcome:
        path = self._bin_dir / name
        present = path.exists() or path.is_symlink()
        ownership_verified = self._ownership.owns(path) if present else False
        return DiskBinaryOutcome(
            binary_name=name,
            path=str(path),
            was_present=present,
            ownership_verified=ownership_verified,
            removed=False,
            verified_clean=not present,
            remediation=self._remediation(path),
        )

    def _sweep_one(self, name: str) -> DiskBinaryOutcome:
        path = self._bin_dir / name
        remediation = self._remediation(path)
        if not (path.exists() or path.is_symlink()):
            return DiskBinaryOutcome(
                binary_name=name,
                path=str(path),
                was_present=False,
                ownership_verified=False,
                removed=False,
                verified_clean=True,
                remediation=remediation,
            )
        ownership_verified = self._ownership.owns(path)
        if not ownership_verified:
            logger.warning(
                "legacy disk binary %s present but not verified as a %s shim; "
                "left in place",
                path,
                _UV_TOOL_PACKAGE,
            )
            return DiskBinaryOutcome(
                binary_name=name,
                path=str(path),
                was_present=True,
                ownership_verified=False,
                removed=False,
                verified_clean=False,
                remediation=remediation,
            )
        path.unlink(missing_ok=True)
        # Re-check the real filesystem state rather than trust unlink()
        # completing without raising -- the same distrust-the-first-signal
        # discipline LegacySweep applies to bootout's exit code.
        verified_clean = not (path.exists() or path.is_symlink())
        return DiskBinaryOutcome(
            binary_name=name,
            path=str(path),
            was_present=True,
            ownership_verified=True,
            removed=True,
            verified_clean=verified_clean,
            remediation=remediation,
        )

    @staticmethod
    def _remediation(path: Path) -> str:
        # `readlink -f` is BSD-incompatible (macOS readlink lacks -f by
        # default); `ls -la` shows the symlink target on both macOS and
        # Linux without relying on a GNU-only flag.
        return f"ls -la {path}"
