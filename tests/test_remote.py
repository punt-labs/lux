"""Tests for punt_lux.remote -- mcp-proxy config read/write."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux.remote import (
    delete_proxy_config,
    read_proxy_config,
    write_proxy_config,
)


@pytest.fixture()
def config_dir(tmp_path: Path):
    """Redirect MCP_PROXY_CONFIG_PATH to a temp directory."""
    fake_path = tmp_path / "mcp-proxy" / "lux.toml"
    with patch("punt_lux.remote.MCP_PROXY_CONFIG_PATH", fake_path):
        yield fake_path


class TestWriteProxyConfig:
    def test_creates_file_with_content(self, config_dir: Path):
        write_proxy_config("ws://127.0.0.1:8430/mcp")
        assert config_dir.exists()
        content = config_dir.read_text()
        assert "[lux]" in content
        assert 'url = "ws://127.0.0.1:8430/mcp"' in content

    def test_creates_parent_directories(self, config_dir: Path):
        assert not config_dir.parent.exists()
        write_proxy_config("ws://127.0.0.1:8430/mcp")
        assert config_dir.parent.is_dir()

    def test_file_permissions(self, config_dir: Path):
        write_proxy_config("ws://127.0.0.1:8430/mcp")
        mode = stat.S_IMODE(config_dir.stat().st_mode)
        assert mode == 0o600

    def test_escapes_special_characters(self, config_dir: Path):
        write_proxy_config('ws://host:8430/mcp?key="val"')
        content = config_dir.read_text()
        assert r"\"val\"" in content

    def test_overwrites_existing(self, config_dir: Path):
        write_proxy_config("ws://old:8430/mcp")
        write_proxy_config("ws://new:8430/mcp")
        content = config_dir.read_text()
        assert "ws://new:8430/mcp" in content
        assert "ws://old:8430/mcp" not in content


class TestReadProxyConfig:
    def test_returns_empty_when_missing(self, config_dir: Path):
        result = read_proxy_config()
        assert result == {}

    def test_reads_valid_config(self, config_dir: Path):
        write_proxy_config("ws://127.0.0.1:8430/mcp")
        result = read_proxy_config()
        assert "lux" in result
        assert result["lux"]["url"] == "ws://127.0.0.1:8430/mcp"

    def test_raises_on_malformed(self, config_dir: Path):
        config_dir.parent.mkdir(parents=True, exist_ok=True)
        config_dir.write_text("not valid toml [[[")
        with pytest.raises(ValueError, match="Malformed config"):
            read_proxy_config()


class TestDeleteProxyConfig:
    def test_returns_false_when_missing(self, config_dir: Path):
        assert delete_proxy_config() is False

    def test_removes_lux_section(self, config_dir: Path):
        write_proxy_config("ws://127.0.0.1:8430/mcp")
        assert delete_proxy_config() is True
        # File should be gone since [lux] was the only section
        assert not config_dir.exists()

    def test_preserves_other_sections(self, config_dir: Path):
        config_dir.parent.mkdir(parents=True, exist_ok=True)
        content = '[other]\nkey = "value"\n\n[lux]\nurl = "ws://127.0.0.1:8430/mcp"\n'
        config_dir.write_text(content)
        assert delete_proxy_config() is True
        remaining = config_dir.read_text()
        assert "[other]" in remaining
        assert "[lux]" not in remaining

    def test_returns_false_when_no_lux_section(self, config_dir: Path):
        config_dir.parent.mkdir(parents=True, exist_ok=True)
        config_dir.write_text('[other]\nkey = "value"\n')
        assert delete_proxy_config() is False
