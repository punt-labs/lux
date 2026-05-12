"""Remote luxd configuration via mcp-proxy config file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

MCP_PROXY_CONFIG_PATH: Path = Path.home() / ".punt-labs" / "mcp-proxy" / "lux.toml"


def _toml_escape(value: str) -> str:
    """Escape a string value for use inside a TOML basic string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _serialize_config(config: dict[str, Any]) -> str:
    """Serialize a flat-section TOML config to string.

    The mcp-proxy config format is always flat sections with string values,
    so a minimal serializer suffices (tomllib is read-only).
    """
    lines: list[str] = []
    for section, values in config.items():
        lines.append(f"[{section}]\n")
        if isinstance(values, dict):
            for key, val in values.items():  # pyright: ignore[reportUnknownVariableType]
                lines.append(f'{key} = "{_toml_escape(str(val))}"\n')  # pyright: ignore[reportUnknownArgumentType]
        lines.append("\n")
    return "".join(lines)


def _atomic_write(content: str) -> None:
    """Write content to MCP_PROXY_CONFIG_PATH atomically, chmod 0600."""
    MCP_PROXY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MCP_PROXY_CONFIG_PATH.with_suffix(".tmp")
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
        tmp.replace(MCP_PROXY_CONFIG_PATH)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_proxy_config() -> dict[str, Any]:
    """Return parsed mcp-proxy config, or {} if file does not exist."""
    if not MCP_PROXY_CONFIG_PATH.exists():
        return {}
    try:
        return tomllib.loads(MCP_PROXY_CONFIG_PATH.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Malformed config at {MCP_PROXY_CONFIG_PATH}: {exc}. "
            "Delete the file and run 'lux setup-proxy' again."
        ) from exc


def write_proxy_config(url: str) -> None:
    """Write [lux] section to mcp-proxy config file, preserving other sections."""
    existing = read_proxy_config()
    existing["lux"] = {"url": url}
    _atomic_write(_serialize_config(existing))


def delete_proxy_config() -> bool:
    """Remove [lux] section from mcp-proxy config. Return False if nothing to remove."""
    existing = read_proxy_config()
    if "lux" not in existing:
        return False
    del existing["lux"]
    if not existing:
        MCP_PROXY_CONFIG_PATH.unlink(missing_ok=True)
    else:
        _atomic_write(_serialize_config(existing))
    return True
