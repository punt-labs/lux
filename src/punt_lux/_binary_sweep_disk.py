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
import subprocess
from pathlib import Path
from typing import Self, final

from punt_lux._binary_sweep import BinarySweepReport, DiskBinaryOutcome
from punt_lux._service_errors import ServiceMigrationError
from punt_lux._service_spec import ServiceSpec

logger = logging.getLogger(__name__)

__all__ = ["DiskBinaryLegacySweep"]

# uv's own tool-install directory layout is package-scoped: <uv tool dir>/<pkg>/bin/.
_UV_TOOL_PACKAGE = "punt-lux"


@final
class DiskBinaryLegacySweep:
    """Remove uv-tool shims left behind by a ``[project.scripts]`` rename."""

    __slots__ = ("_bin_dir", "_spec", "_tool_root", "_tool_root_resolved")
    _bin_dir: Path
    _spec: ServiceSpec
    # Lazily resolved and cached on first use, not in __new__ -- a service
    # with an empty legacy_binary_names tuple (DISPLAY_SPEC) or a fake bin
    # dir with nothing present never needs to shell out at all.
    _tool_root: Path | None  # None only if `uv tool dir` could not run
    _tool_root_resolved: bool

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._bin_dir = Path.home() / ".local" / "bin"
        self._tool_root = None
        self._tool_root_resolved = False
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
        ownership_verified = self._is_ours(path) if present else False
        return DiskBinaryOutcome(
            binary_name=name,
            path=str(path),
            was_present=present,
            ownership_verified=ownership_verified,
            removed=False,
            verified_clean=not present,
            fix_command=self._fix_command(path),
        )

    def _sweep_one(self, name: str) -> DiskBinaryOutcome:
        path = self._bin_dir / name
        fix_command = self._fix_command(path)
        if not (path.exists() or path.is_symlink()):
            return DiskBinaryOutcome(
                binary_name=name,
                path=str(path),
                was_present=False,
                ownership_verified=False,
                removed=False,
                verified_clean=True,
                fix_command=fix_command,
            )
        ownership_verified = self._is_ours(path)
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
                fix_command=fix_command,
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
            fix_command=fix_command,
        )

    def _resolve_tool_root(self) -> Path | None:
        """Shell out to ``uv tool dir`` once; cache the result on the instance.

        Absence of ``uv`` on ``PATH`` means "cannot verify," which means
        "do not remove" -- the same fail-closed posture
        :meth:`~punt_lux._port_guard.PortGuard.guard` takes for a missing
        ``lsof``.
        """
        try:
            result = subprocess.run(
                ["uv", "tool", "dir"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("uv not found on PATH; cannot verify legacy binaries")
            return None
        if result.returncode != 0:
            logger.warning(
                "uv tool dir exited %d; cannot verify legacy binaries",
                result.returncode,
            )
            return None
        stdout = result.stdout.strip()
        if not stdout or not Path(stdout).is_absolute():
            logger.warning(
                "uv tool dir printed no usable path (%r); cannot verify "
                "legacy binaries",
                stdout,
            )
            return None
        return Path(stdout).resolve() / _UV_TOOL_PACKAGE

    def _is_ours(self, path: Path) -> bool:
        """Return whether ``path`` ultimately resolves inside this package's tool dir.

        A path-component containment check (``Path.is_relative_to``), not a
        string prefix comparison -- ``str.startswith()`` would accept a
        sibling tool directory whose name merely starts with ours (e.g.
        ``punt-lux-devtools``), unlinking a completely different package's
        shim. See ``docs/architecture/binary-rename-migration.md`` §2.4.
        """
        if not self._tool_root_resolved:
            self._tool_root = self._resolve_tool_root()
            self._tool_root_resolved = True
        if self._tool_root is None:
            return False
        target = self._resolve_shim_target(path)
        if target is None:
            return False
        return target.is_relative_to(self._tool_root)

    @staticmethod
    def _resolve_shim_target(path: Path) -> Path | None:
        """Follow whichever shim shape is actually on disk.

        A symlink is resolved directly. A plain file is read for a shebang
        line naming the interpreter, the shape a future uv version could use
        instead of a symlink. Anything else (directory, binary, broken
        symlink with no resolvable target) yields ``None``.
        """
        if path.is_symlink():
            return path.resolve()
        if path.is_file():
            try:
                with path.open(encoding="utf-8", errors="replace") as fh:
                    first_line = fh.readline()
            except OSError:
                return None
            if first_line.startswith("#!"):
                return Path(first_line[2:].strip()).resolve()
        return None

    @staticmethod
    def _fix_command(path: Path) -> str:
        # `readlink -f` is BSD-incompatible (macOS readlink lacks -f by
        # default); `ls -la` shows the symlink target on both macOS and
        # Linux without relying on a GNU-only flag.
        return f"ls -la {path}"
