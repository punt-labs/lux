"""CaPaths — resolve the personal CA's on-disk location.

Mirrors :class:`~punt_lux.hub_paths.HubPaths`'s single-root-directory shape:
one directory under ``~/.punt-labs/lux/``, every material path derived from
it. system.tex §"Authentication and Enrollment" names the directory and its
permission discipline explicitly: ``0700`` directory, ``0600`` private key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self, final

__all__ = ["CaPaths"]


@final
class CaPaths:
    """Resolve the personal CA's root key, root certificate, and directory."""

    _dir: Path
    __slots__ = ("_dir",)

    def __new__(cls, root: Path | None = None) -> Self:
        self = super().__new__(cls)
        self._dir = root or Path.home() / ".punt-labs" / "lux" / "ca"
        return self

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
        self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._dir.chmod(0o700)
