"""CaPaths — the personal CA's on-disk location under ``~/.punt-labs/lux/``."""

from __future__ import annotations

from pathlib import Path
from typing import Self, final

from punt_lux.kernel.home_paths import LuxHome

__all__ = ["CaPaths"]


@final
class CaPaths:
    """Resolve the personal CA's root key, root certificate, and directory."""

    _dir: Path
    __slots__ = ("_dir",)

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._dir = root
        return self

    @classmethod
    def default(cls) -> Self:
        """Return the standard CA root: ``~/.punt-labs/lux/ca/``."""
        return cls(LuxHome.resolve().ca)

    @property
    def dir(self) -> Path:
        """Return the CA's root directory: ``~/.punt-labs/lux/ca/``."""
        return self._dir

    @property
    def root_key_path(self) -> Path:
        """Return the CA's private key path — never installed elsewhere."""
        return self._dir / "root.key"

    @property
    def root_cert_path(self) -> Path:
        """Return the CA's self-signed root certificate path."""
        return self._dir / "root.crt"

    def exists(self) -> bool:
        """Return whether a CA is already provisioned at this root."""
        return self.root_key_path.exists() and self.root_cert_path.exists()

    def ensure_dir(self) -> None:
        """Create the CA directory as ``0700`` if it does not already exist."""
        LuxHome.prepare_ca(self._dir)
