"""Atomic byte-preserving file updates for repository integration."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True, slots=True)
class ActivationFile:
    path: Path

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(f".{self.path.name}.punt-import.lock")

    @contextmanager
    def locked(self) -> Generator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
        with os.fdopen(os.open(self.lock_path, flags, 0o600), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self) -> bytes | None:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None

    def write(self, data: bytes) -> None:
        target = self.path.resolve()
        if self.read() == data:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            mode = stat.S_IMODE(target.stat().st_mode)
        except FileNotFoundError:
            mode = 0o644
        with NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            tmp = Path(handle.name)
            try:
                handle.write(data)
                handle.flush()
                tmp.chmod(mode)
                tmp.replace(target)
            finally:
                tmp.unlink(missing_ok=True)
