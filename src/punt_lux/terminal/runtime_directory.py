"""Private runtime directories shared by daemon binding and local launchers."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class RuntimeDirectory:
    @staticmethod
    def prepare(directory: Path) -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError("terminal directory must be owned and not a symlink")
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise PermissionError("terminal directory must have mode 0700")
        for ancestor in directory.parents:
            RuntimeDirectory._ancestor(ancestor)

    @staticmethod
    def _ancestor(path: Path) -> None:
        if path.lstat().st_uid not in (0, os.getuid()):
            raise PermissionError("terminal directory has a foreign-owned ancestor")
        info = path.stat()
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if not sticky_root and info.st_mode & 0o022:
            raise PermissionError("terminal directory has a writable ancestor")
