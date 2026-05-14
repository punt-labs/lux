"""Tests for punt_lux.remote -- mcp-proxy config read/write."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from punt_lux.remote import ProxyConfigFile


@pytest.fixture()
def config_file(tmp_path: Path) -> ProxyConfigFile:
    """Return a ProxyConfigFile pointed at a temp directory."""
    fake_path = tmp_path / "mcp-proxy" / "lux.toml"
    return ProxyConfigFile(fake_path)


class TestWrite:
    def test_creates_file_with_content(self, config_file: ProxyConfigFile) -> None:
        config_file.write("ws://127.0.0.1:8430/mcp")
        assert config_file.path.exists()
        content = config_file.path.read_text()
        assert "[lux]" in content
        assert 'url = "ws://127.0.0.1:8430/mcp"' in content

    def test_creates_parent_directories(self, config_file: ProxyConfigFile) -> None:
        assert not config_file.path.parent.exists()
        config_file.write("ws://127.0.0.1:8430/mcp")
        assert config_file.path.parent.is_dir()

    def test_file_permissions(self, config_file: ProxyConfigFile) -> None:
        config_file.write("ws://127.0.0.1:8430/mcp")
        mode = stat.S_IMODE(config_file.path.stat().st_mode)
        assert mode == 0o600

    def test_escapes_special_characters(self, config_file: ProxyConfigFile) -> None:
        config_file.write('ws://host:8430/mcp?key="val"')
        content = config_file.path.read_text()
        assert r"\"val\"" in content

    def test_overwrites_existing(self, config_file: ProxyConfigFile) -> None:
        config_file.write("ws://old:8430/mcp")
        config_file.write("ws://new:8430/mcp")
        content = config_file.path.read_text()
        assert "ws://new:8430/mcp" in content
        assert "ws://old:8430/mcp" not in content


class TestRead:
    def test_returns_empty_when_missing(self, config_file: ProxyConfigFile) -> None:
        result = config_file.read()
        assert result == {}

    def test_reads_valid_config(self, config_file: ProxyConfigFile) -> None:
        config_file.write("ws://127.0.0.1:8430/mcp")
        result = config_file.read()
        assert "lux" in result
        assert result["lux"]["url"] == "ws://127.0.0.1:8430/mcp"

    def test_raises_on_malformed(self, config_file: ProxyConfigFile) -> None:
        config_file.path.parent.mkdir(parents=True, exist_ok=True)
        config_file.path.write_text("not valid toml [[[")
        with pytest.raises(ValueError, match="Malformed config"):
            config_file.read()


class TestDelete:
    def test_returns_false_when_missing(self, config_file: ProxyConfigFile) -> None:
        assert config_file.delete() is False

    def test_removes_lux_section(self, config_file: ProxyConfigFile) -> None:
        config_file.write("ws://127.0.0.1:8430/mcp")
        assert config_file.delete() is True
        # File should be gone since [lux] was the only section
        assert not config_file.path.exists()

    def test_preserves_other_sections(self, config_file: ProxyConfigFile) -> None:
        config_file.path.parent.mkdir(parents=True, exist_ok=True)
        content = '[other]\nkey = "value"\n\n[lux]\nurl = "ws://127.0.0.1:8430/mcp"\n'
        config_file.path.write_text(content)
        assert config_file.delete() is True
        remaining = config_file.path.read_text()
        assert "[other]" in remaining
        assert "[lux]" not in remaining

    def test_returns_false_when_no_lux_section(
        self, config_file: ProxyConfigFile
    ) -> None:
        config_file.path.parent.mkdir(parents=True, exist_ok=True)
        config_file.path.write_text('[other]\nkey = "value"\n')
        assert config_file.delete() is False
