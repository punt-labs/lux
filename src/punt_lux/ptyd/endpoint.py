"""Private, socket-authoritative endpoint; never unlink another server's node."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path
from typing import Self


class LocalEndpoint:
    """Bind one private socket, refusing insecure or occupied locations."""

    _path: Path
    _listener: socket.socket
    _identity: tuple[int, int] | None
    _closed: bool

    def __new__(cls, path: Path) -> Self:
        path = path.absolute()
        if len(os.fsencode(path)) > 103:
            raise OSError(
                "Unix socket path is too long; choose a shorter --socket path"
            )
        cls._prepare(path.parent)
        self = super().__new__(cls)
        self._path = path
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._closed = False
        self._identity = None
        try:
            self._listener.bind(str(path))  # existing nodes are never removed here
            info = path.lstat()
            self._identity = (info.st_dev, info.st_ino)
            path.chmod(0o600)
            self._listener.listen(16)
            self._listener.settimeout(0.0)
        except BaseException:
            self.close()
            raise
        return self

    @property
    def listener(self) -> socket.socket:
        return self._listener

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._listener.close()
        if self._identity is None:
            return
        try:
            info = self._path.lstat()
        except FileNotFoundError:
            return
        if (info.st_dev, info.st_ino) == self._identity and stat.S_ISSOCK(info.st_mode):
            self._path.unlink()

    @staticmethod
    def _prepare(directory: Path) -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError("terminal directory must be owned and not a symlink")
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise PermissionError("terminal directory must have mode 0700")
        for ancestor in directory.parents:
            LocalEndpoint._check_ancestor(ancestor)

    @staticmethod
    def _check_ancestor(path: Path) -> None:
        if path.lstat().st_uid not in (0, os.getuid()):
            raise PermissionError("terminal directory has a foreign-owned ancestor")
        info = path.stat()
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if not sticky_root and info.st_mode & 0o022:
            raise PermissionError("terminal directory has a writable ancestor")
