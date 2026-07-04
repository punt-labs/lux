"""Tests for the HubPaths class in punt_lux.hub_paths."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from punt_lux.hub_paths import HubPaths


class TestHubPaths:
    def test_dir_defaults_to_home(self):
        assert HubPaths().dir == Path.home() / ".punt-labs" / "lux"

    def test_dir_honors_root_override(self, tmp_path: Path):
        assert HubPaths(tmp_path).dir == tmp_path

    def test_pid_path(self, tmp_path: Path):
        assert HubPaths(tmp_path).pid_path == tmp_path / "hub.pid"

    def test_port_path(self, tmp_path: Path):
        assert HubPaths(tmp_path).port_path == tmp_path / "hub.port"

    def test_log_dir(self, tmp_path: Path):
        assert HubPaths(tmp_path).log_dir == tmp_path / "logs"


class TestReadPort:
    def test_returns_none_when_missing(self, tmp_path: Path):
        assert HubPaths(tmp_path).read_port() is None

    def test_reads_valid_port(self, tmp_path: Path):
        (tmp_path / "hub.port").write_text("8430\n")
        assert HubPaths(tmp_path).read_port() == 8430

    def test_returns_none_on_invalid(self, tmp_path: Path):
        (tmp_path / "hub.port").write_text("not_a_number")
        assert HubPaths(tmp_path).read_port() is None


class TestIsRunning:
    def test_returns_false_when_no_pid(self, tmp_path: Path):
        assert HubPaths(tmp_path).is_running() is False

    def test_returns_false_on_dead_pid(self, tmp_path: Path):
        (tmp_path / "hub.pid").write_text("999999999")
        assert HubPaths(tmp_path).is_running() is False

    def test_returns_true_for_current_process(self, tmp_path: Path):
        (tmp_path / "hub.pid").write_text(str(os.getpid()))
        assert HubPaths(tmp_path).is_running() is True

    def test_returns_false_on_corrupt_pid(self, tmp_path: Path):
        (tmp_path / "hub.pid").write_text("garbage")
        assert HubPaths(tmp_path).is_running() is False

    def test_non_positive_pid_is_not_running(self, tmp_path: Path):
        """A corrupt PID file of '0' or '-1' reads as not running, never signalled."""
        pid_file = tmp_path / "hub.pid"
        paths = HubPaths(tmp_path)
        for corrupt in ("0", "-1"):
            pid_file.write_text(corrupt)
            with patch("punt_lux.hub_paths.os.kill") as kill:
                assert paths.is_running() is False
            kill.assert_not_called()
