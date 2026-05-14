"""Tests for punt_lux.config — YAML frontmatter config read/write."""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.config import (
    ConfigManager,
    LuxConfig,
)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / ".punt-labs" / "lux.md"


@pytest.fixture
def mgr(config_path: Path) -> ConfigManager:
    return ConfigManager(config_path)


# ---------------------------------------------------------------------------
# ConfigManager.read
# ---------------------------------------------------------------------------


class TestReadConfig:
    def test_defaults_when_missing(self, mgr: ConfigManager) -> None:
        cfg = mgr.read()
        assert cfg == LuxConfig(display="n")

    def test_reads_display_y(self, config_path: Path, mgr: ConfigManager) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "y"\n---\n')
        cfg = mgr.read()
        assert cfg.display == "y"

    def test_invalid_display_falls_back(
        self, config_path: Path, mgr: ConfigManager
    ) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "maybe"\n---\n')
        cfg = mgr.read()
        assert cfg.display == "n"

    def test_ignores_body_fields(self, config_path: Path, mgr: ConfigManager) -> None:
        """A display: line in the body must not override frontmatter."""
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "n"\n---\n\ndisplay: "y"\n')
        cfg = mgr.read()
        assert cfg.display == "n"


# ---------------------------------------------------------------------------
# ConfigManager.write_field
# ---------------------------------------------------------------------------


class TestWriteField:
    def test_creates_file(self, config_path: Path, mgr: ConfigManager) -> None:
        mgr.write_field("display", "y")
        assert config_path.exists()
        text = config_path.read_text()
        assert 'display: "y"' in text
        assert text.startswith("---\n")
        assert text.endswith("\n")

    def test_updates_existing(self, config_path: Path, mgr: ConfigManager) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "n"\n---\n')
        mgr.write_field("display", "y")
        assert mgr.read().display == "y"

    def test_inserts_new_field(self, config_path: Path, mgr: ConfigManager) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text("---\n---\n")
        mgr.write_field("display", "y")
        assert mgr.read().display == "y"

    def test_rejects_unknown_key(self, mgr: ConfigManager) -> None:
        with pytest.raises(ValueError, match="Unknown config key"):
            mgr.write_field("bogus", "x")

    def test_preserves_body(self, config_path: Path, mgr: ConfigManager) -> None:
        """Write must not corrupt markdown body content."""
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "n"\n---\n\n# Notes\nSome text.\n')
        mgr.write_field("display", "y")
        text = config_path.read_text()
        assert "# Notes" in text
        assert "Some text." in text
        assert mgr.read().display == "y"

    def test_trailing_newline(self, config_path: Path, mgr: ConfigManager) -> None:
        """Written file must end with a newline (POSIX)."""
        mgr.write_field("display", "y")
        text = config_path.read_text()
        assert text.endswith("\n")

    def test_explicit_utf8_encoding(
        self, config_path: Path, mgr: ConfigManager
    ) -> None:
        """Writes use explicit UTF-8 encoding."""
        mgr.write_field("display", "y")
        # Read back with explicit encoding to verify
        text = config_path.read_text(encoding="utf-8")
        assert 'display: "y"' in text


# ---------------------------------------------------------------------------
# ConfigManager.path property
# ---------------------------------------------------------------------------


class TestConfigManagerPath:
    def test_path_returns_configured_path(
        self, config_path: Path, mgr: ConfigManager
    ) -> None:
        assert mgr.path == config_path
