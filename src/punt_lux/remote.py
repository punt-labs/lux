"""Remote luxd configuration via mcp-proxy config file."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

MCP_PROXY_CONFIG_PATH: Path = Path.home() / ".punt-labs" / "mcp-proxy" / "lux.toml"


def _toml_escape(value: str) -> str:
    """Escape a string value for use inside a TOML basic string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
    """Write [lux] section to mcp-proxy config file atomically, chmod 0600."""
    content = f'[lux]\nurl = "{_toml_escape(url)}"\n'
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


def delete_proxy_config() -> bool:
    """Remove [lux] section from mcp-proxy config. Return False if nothing to remove."""
    if not MCP_PROXY_CONFIG_PATH.exists():
        return False
    raw = MCP_PROXY_CONFIG_PATH.read_text()
    # Strip the [lux] block including all [lux.*] subsections.
    cleaned, n_subs = re.subn(
        r"\[lux\].*?(?=\n\[(?!lux)[^\]]*\]|\Z)", "", raw, flags=re.DOTALL
    )
    if n_subs == 0:
        return False
    stripped = cleaned.strip()
    if stripped:
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
                f.write(stripped + "\n")
            tmp.replace(MCP_PROXY_CONFIG_PATH)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    else:
        MCP_PROXY_CONFIG_PATH.unlink()
    return True
