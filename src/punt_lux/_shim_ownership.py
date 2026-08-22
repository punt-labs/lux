"""ShimOwnership -- verify a disk shim resolves inside a package's uv tool dir.

Split out of :mod:`~punt_lux._binary_sweep_disk` (composition, not
inheritance -- PY-IC-1): resolving ``uv tool dir`` and following a shim to
its real target is a self-contained concern with its own lazy-cache state,
independent of the sweep/diagnose orchestration that owns it.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Self, final

logger = logging.getLogger(__name__)

__all__ = ["ShimOwnership"]


@final
class ShimOwnership:
    """Answer whether a disk shim belongs to one uv-tool-installed package."""

    __slots__ = ("_package", "_tool_root", "_tool_root_resolved")
    _package: str
    # Lazily resolved and cached on first use -- a service with an empty
    # legacy_binary_names tuple (DISPLAY_SPEC) or a fake bin dir with
    # nothing present never needs to shell out at all.
    _tool_root: Path | None  # None only if `uv tool dir` could not run
    _tool_root_resolved: bool

    def __new__(cls, package: str) -> Self:
        self = super().__new__(cls)
        self._package = package
        self._tool_root = None
        self._tool_root_resolved = False
        return self

    def owns(self, path: Path) -> bool:
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
        return Path(stdout).resolve() / self._package

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
