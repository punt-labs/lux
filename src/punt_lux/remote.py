"""Remote luxd configuration via mcp-proxy config file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import (
    Any,  # pyright: ignore[reportExplicitAny]
    Self,
)

_DEFAULT_PATH: Path = Path.home() / ".punt-labs" / "mcp-proxy" / "lux.toml"


class ProxyConfigFile:
    """Read, write, and delete the mcp-proxy TOML config for luxd."""

    _path: Path

    def __new__(cls, path: Path | None = None) -> Self:
        self = super().__new__(cls)
        self._path = path or _DEFAULT_PATH
        return self

    @property
    def path(self) -> Path:
        """Return the resolved config file path."""
        return self._path

    def read(self) -> dict[str, Any]:  # pyright: ignore[reportExplicitAny]
        """Return parsed mcp-proxy config, or {} if file does not exist."""
        if not self._path.exists():
            return {}
        try:
            return tomllib.loads(self._path.read_text())
        except tomllib.TOMLDecodeError as exc:
            msg = (
                f"Malformed config at {self._path}: {exc}. "
                "Delete the file and run 'lux setup-proxy' again."
            )
            raise ValueError(msg) from exc

    def write(self, url: str) -> None:
        """Write [lux] section to config file, preserving other sections."""
        existing = self.read()
        existing["lux"] = {"url": url}
        self._atomic_write(self._serialize_config(existing))

    def delete(self) -> bool:
        """Remove [lux] section from config. Return False if nothing to remove."""
        existing = self.read()
        if "lux" not in existing:
            return False
        del existing["lux"]
        if not existing:
            self._path.unlink(missing_ok=True)
        else:
            self._atomic_write(self._serialize_config(existing))
        return True

    def _atomic_write(self, content: str) -> None:
        """Write content to the config path atomically, chmod 0600."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(str(tmp), flags, 0o600)
        try:
            f = os.fdopen(fd, "w")
        except BaseException:
            os.close(fd)
            tmp.unlink(missing_ok=True)
            raise
        try:
            with f:
                f.write(content)
            tmp.replace(self._path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _toml_escape(value: str) -> str:
        """Escape a string value for use inside a TOML basic string."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _serialize_config(config: dict[str, Any]) -> str:  # pyright: ignore[reportExplicitAny]
        """Serialize a flat-section TOML config to string."""
        lines: list[str] = []
        for section, values in config.items():
            lines.append(f"[{section}]\n")
            if isinstance(values, dict):
                for key, val in values.items():  # pyright: ignore[reportUnknownVariableType]
                    escaped = ProxyConfigFile._toml_escape(str(val))  # pyright: ignore[reportUnknownArgumentType]
                    lines.append(f'{key} = "{escaped}"\n')
            lines.append("\n")
        return "".join(lines)
