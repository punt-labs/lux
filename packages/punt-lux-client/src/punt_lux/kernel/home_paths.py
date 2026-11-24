"""Resolve Lux-owned paths relative to the user's home directory."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import Self, final

_NAMESPACE = ".punt-labs"


@final
class LuxHome:
    """Own the locations of Lux's home-scoped files and session claims."""

    _root: Path
    __slots__ = ("_root",)

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    @classmethod
    def resolve(cls) -> Self:
        """Resolve the product root without falling back to the checkout."""
        home = Path.home()
        if not home.is_absolute():
            raise RuntimeError("Lux requires an absolute home directory")
        return cls(home / _NAMESPACE / "lux")

    @property
    def root(self) -> Path:
        """Return the canonical product root."""
        return self._root

    @property
    def ca(self) -> Path:
        """Return the directory containing the personal CA."""
        return self._root / "ca"

    @staticmethod
    def prepare_ca(directory: Path) -> None:
        """Create the CA directory and normalize its permissions."""
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)

    @property
    def display_stderr(self) -> Path:
        """Return the captured Display stderr path."""
        return self._root / "logs" / "luxd-display-stderr.log"

    @property
    def pty_socket(self) -> Path:
        """Return the socket path shared by the terminal daemon and Display."""
        return self._root / "pty" / "luxd-pty.sock"

    @classmethod
    def display_pty_socket(cls) -> Path:
        """Resolve the socket used by Display, honoring its environment override."""
        return cls.terminal_socket(os.environ.get("LUX_PTY_SOCKET"))

    @classmethod
    def terminal_socket(cls, override: str | Path | None) -> Path:
        """Use an explicit socket without requiring a home directory."""
        return Path(override) if override is not None else cls.resolve().pty_socket

    def prepare_root(self) -> Path:
        """Create the Lux root or tighten an existing root owned by this user."""
        namespace = self._root.parent
        home = namespace.parent.resolve(strict=True)
        self._require_claim_ancestors(home)
        self._require_claim_parent(home)
        namespace = self._prepare_namespace(home / namespace.name)
        root = namespace / self._root.name
        self._make_private(root)
        return root

    def _prepare_namespace(self, namespace: Path) -> Path:
        if namespace.name != _NAMESPACE:
            namespace.mkdir(exist_ok=True, mode=0o700)
            self._require_claim_parent(namespace)
            return namespace
        if namespace.is_symlink():
            if namespace.lstat().st_uid not in (0, os.getuid()):
                raise PermissionError(f"Lux state symlink is not trusted: {namespace}")
            namespace = namespace.resolve(strict=True)
            self._require_claim_ancestors(namespace)
        self._make_private(namespace)
        return namespace

    @staticmethod
    def _directory_entry(directory: Path) -> os.stat_result:
        with suppress(FileExistsError):
            directory.mkdir(mode=0o700)
        return directory.lstat()

    @classmethod
    def _make_private(cls, directory: Path) -> None:
        info = cls._directory_entry(directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError(
                f"Lux state path is not an owned directory: {directory}"
            )
        mode = stat.S_IMODE(info.st_mode)
        private_mode = 0o700 | (mode & stat.S_ISGID)
        if mode != private_mode:
            directory.chmod(private_mode)

    def session_claim(self, program: str, session_pid: int) -> Path:
        """Provision the private session directory and return the claim path."""
        sessions = self.prepare_root() / "sessions"
        info = self._directory_entry(sessions)
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) & ~stat.S_ISGID != 0o700
            or info.st_uid != os.getuid()
        ):
            raise PermissionError(f"Lux session directory is not private: {sessions}")
        return sessions / f"{program}-{session_pid}.pid"

    @staticmethod
    def _require_claim_parent(directory: Path) -> None:
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()):
            raise PermissionError(
                f"Lux session ancestor is not an owned directory: {directory}"
            )
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if info.st_mode & 0o022 and not sticky_root:
            raise PermissionError(f"Lux session ancestor is writable: {directory}")

    @classmethod
    def _require_claim_ancestors(cls, directory: Path) -> None:
        for parent in reversed(directory.parents):
            cls._require_claim_parent(parent)
