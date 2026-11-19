"""Private, socket-authoritative endpoint; never unlink another server's node."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path
from typing import Self

from punt_lux.terminal.runtime_directory import RuntimeDirectory


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
        RuntimeDirectory.prepare(path.parent)
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
