"""Atomic same-directory config writes, shared by the service backends."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Self, final

__all__ = ["write_config_atomic"]


@final
class AtomicConfigWriter:
    """Write file content atomically via a same-directory temp file + rename.

    Shared by :class:`~punt_lux._backend_launchd.LaunchdBackend` and
    :class:`~punt_lux._backend_systemd.SystemdBackend` -- both need the same
    guarantee (readers never observe a partially-written plist or unit file)
    and had identical bodies before this extraction.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def write(self, path: Path, content: str) -> None:
        """Write ``content`` to ``path``, replacing it only once it is whole."""
        tmp_path = path.with_name(path.name + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(str(tmp_path), flags, 0o600)
        try:
            f = os.fdopen(fd, "w")
        except BaseException:
            os.close(fd)
            tmp_path.unlink(missing_ok=True)
            raise
        try:
            with f:
                f.write(content)
            tmp_path.replace(path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise


write_config_atomic: AtomicConfigWriter = AtomicConfigWriter()
