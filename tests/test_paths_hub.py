"""Tests for hub path functions in punt_lux.paths."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from punt_lux.paths import (
    hub_dir,
    hub_log_dir,
    hub_pid_path,
    hub_port_path,
    is_hub_running,
    read_hub_port,
)


class TestHubPaths:
    def test_hub_dir(self):
        result = hub_dir()
        assert result == Path.home() / ".punt-labs" / "lux"

    def test_hub_pid_path(self):
        result = hub_pid_path()
        assert result.name == "hub.pid"
        assert result.parent == hub_dir()

    def test_hub_port_path(self):
        result = hub_port_path()
        assert result.name == "hub.port"
        assert result.parent == hub_dir()

    def test_hub_log_dir(self):
        result = hub_log_dir()
        assert result == hub_dir() / "logs"


class TestReadHubPort:
    def test_returns_none_when_missing(self, tmp_path: Path):
        fake_dir = tmp_path / ".punt-labs" / "lux"
        with patch("punt_lux.paths.hub_port_path", return_value=fake_dir / "hub.port"):
            assert read_hub_port() is None

    def test_reads_valid_port(self, tmp_path: Path):
        port_file = tmp_path / "hub.port"
        port_file.write_text("8430\n")
        with patch("punt_lux.paths.hub_port_path", return_value=port_file):
            assert read_hub_port() == 8430

    def test_returns_none_on_invalid(self, tmp_path: Path):
        port_file = tmp_path / "hub.port"
        port_file.write_text("not_a_number")
        with patch("punt_lux.paths.hub_port_path", return_value=port_file):
            assert read_hub_port() is None


class TestIsHubRunning:
    def test_returns_false_when_no_pid(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        with patch("punt_lux.paths.hub_pid_path", return_value=pid_file):
            assert is_hub_running() is False

    def test_returns_false_on_dead_pid(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("999999999")
        with patch("punt_lux.paths.hub_pid_path", return_value=pid_file):
            assert is_hub_running() is False

    def test_returns_true_for_current_process(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text(str(os.getpid()))
        with patch("punt_lux.paths.hub_pid_path", return_value=pid_file):
            assert is_hub_running() is True

    def test_returns_false_on_corrupt_pid(self, tmp_path: Path):
        pid_file = tmp_path / "hub.pid"
        pid_file.write_text("garbage")
        with patch("punt_lux.paths.hub_pid_path", return_value=pid_file):
            assert is_hub_running() is False
