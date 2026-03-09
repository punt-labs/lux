"""Tests for punt_lux.config — YAML frontmatter config read/write."""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.config import (
    LuxConfig,
    read_config,
    read_field,
    write_field,
)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / ".lux" / "config.md"


# ---------------------------------------------------------------------------
# read_field
# ---------------------------------------------------------------------------


class TestReadField:
    def test_missing_file(self, config_path: Path) -> None:
        assert read_field("display", config_path) is None

    def test_reads_quoted_value(self, config_path: Path) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "y"\n---\n')
        assert read_field("display", config_path) == "y"

    def test_reads_unquoted_value(self, config_path: Path) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text("---\ndisplay: n\n---\n")
        assert read_field("display", config_path) == "n"

    def test_absent_field(self, config_path: Path) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text("---\n---\n")
        assert read_field("display", config_path) is None

    def test_ignores_body_content(self, config_path: Path) -> None:
        """Fields in markdown body must not be read as config."""
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            '---\ndisplay: "n"\n---\n\nSome markdown with display: y in it.\n'
        )
        assert read_field("display", config_path) == "n"


# ---------------------------------------------------------------------------
# read_config
# ---------------------------------------------------------------------------


class TestReadConfig:
    def test_defaults_when_missing(self, config_path: Path) -> None:
        cfg = read_config(config_path)
        assert cfg == LuxConfig(display="n")

    def test_reads_display_y(self, config_path: Path) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "y"\n---\n')
        cfg = read_config(config_path)
        assert cfg.display == "y"

    def test_invalid_display_falls_back(self, config_path: Path) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "maybe"\n---\n')
        cfg = read_config(config_path)
        assert cfg.display == "n"

    def test_ignores_body_fields(self, config_path: Path) -> None:
        """A display: line in the body must not override frontmatter."""
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "n"\n---\n\ndisplay: "y"\n')
        cfg = read_config(config_path)
        assert cfg.display == "n"


# ---------------------------------------------------------------------------
# write_field
# ---------------------------------------------------------------------------


class TestWriteField:
    def test_creates_file(self, config_path: Path) -> None:
        write_field("display", "y", config_path)
        assert config_path.exists()
        text = config_path.read_text()
        assert 'display: "y"' in text
        assert text.startswith("---\n")
        assert text.endswith("\n")

    def test_updates_existing(self, config_path: Path) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "n"\n---\n')
        write_field("display", "y", config_path)
        assert read_field("display", config_path) == "y"

    def test_inserts_new_field(self, config_path: Path) -> None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text("---\n---\n")
        write_field("display", "y", config_path)
        assert read_field("display", config_path) == "y"

    def test_rejects_unknown_key(self, config_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown config key"):
            write_field("bogus", "x", config_path)

    def test_preserves_body(self, config_path: Path) -> None:
        """Write must not corrupt markdown body content."""
        config_path.parent.mkdir(parents=True)
        config_path.write_text('---\ndisplay: "n"\n---\n\n# Notes\nSome text.\n')
        write_field("display", "y", config_path)
        text = config_path.read_text()
        assert "# Notes" in text
        assert "Some text." in text
        assert read_field("display", config_path) == "y"

    def test_trailing_newline(self, config_path: Path) -> None:
        """Written file must end with a newline (POSIX)."""
        write_field("display", "y", config_path)
        text = config_path.read_text()
        assert text.endswith("\n")

    def test_explicit_utf8_encoding(self, config_path: Path) -> None:
        """Writes use explicit UTF-8 encoding."""
        write_field("display", "y", config_path)
        # Read back with explicit encoding to verify
        text = config_path.read_text(encoding="utf-8")
        assert 'display: "y"' in text
