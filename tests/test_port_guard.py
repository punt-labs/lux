"""Tests for PortGuard -- free/ours/foreign/unknown, fail-closed on guard()."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from punt_lux._port_guard import PortGuard, PortGuardResult
from punt_lux._service_errors import PortConflictError
from punt_lux.service import DISPLAY_SPEC, HUB_SPEC


class TestPortGuardCheck:
    def test_no_fixed_port_reports_free(self) -> None:
        guard = PortGuard(DISPLAY_SPEC)
        assert guard.check() == PortGuardResult(status="free", pid=None)

    def test_no_holder_reports_free(self) -> None:
        guard = PortGuard(HUB_SPEC)
        with patch("punt_lux._port_guard.subprocess.run") as run:
            run.return_value.stdout = ""
            result = guard.check()
        assert result.status == "free"
        assert result.pid is None

    def test_our_pid_reports_ours(self) -> None:
        guard = PortGuard(HUB_SPEC)
        with (
            patch("punt_lux._port_guard.subprocess.run") as run,
            patch("punt_lux._port_guard.pgrep_pid", return_value=4242),
        ):
            run.return_value.stdout = "4242\n"
            result = guard.check()
        assert result.status == "ours"
        assert result.pid == 4242

    def test_foreign_pid_reports_foreign(self) -> None:
        guard = PortGuard(HUB_SPEC)
        with (
            patch("punt_lux._port_guard.subprocess.run") as run,
            patch("punt_lux._port_guard.pgrep_pid", return_value=None),
        ):
            run.return_value.stdout = "14100\n"
            result = guard.check()
        assert result.status == "foreign"
        assert result.pid == 14100

    def test_missing_lsof_reports_unknown_not_free(self) -> None:
        """A query that cannot determine the answer reports that as data."""
        guard = PortGuard(HUB_SPEC)
        with patch(
            "punt_lux._port_guard.subprocess.run", side_effect=FileNotFoundError
        ):
            result = guard.check()
        assert result.status == "unknown"
        assert result.pid is None


class TestPortGuardGuard:
    def test_free_passes(self) -> None:
        guard = PortGuard(HUB_SPEC)
        with patch("punt_lux._port_guard.subprocess.run") as run:
            run.return_value.stdout = ""
            guard.guard()  # must not raise

    def test_ours_passes(self) -> None:
        guard = PortGuard(HUB_SPEC)
        with (
            patch("punt_lux._port_guard.subprocess.run") as run,
            patch("punt_lux._port_guard.pgrep_pid", return_value=4242),
        ):
            run.return_value.stdout = "4242\n"
            guard.guard()  # must not raise

    def test_foreign_raises(self) -> None:
        guard = PortGuard(HUB_SPEC)
        with (
            patch("punt_lux._port_guard.subprocess.run") as run,
            patch("punt_lux._port_guard.pgrep_pid", return_value=None),
            pytest.raises(PortConflictError, match="14100"),
        ):
            run.return_value.stdout = "14100\n"
            guard.guard()

    def test_missing_lsof_raises_never_assumes_safe(self) -> None:
        """guard() is fail-closed: 'cannot verify' must raise, not pass."""
        guard = PortGuard(HUB_SPEC)
        with (
            patch("punt_lux._port_guard.subprocess.run", side_effect=FileNotFoundError),
            pytest.raises(PortConflictError, match="lsof"),
        ):
            guard.guard()

    def test_no_fixed_port_never_raises(self) -> None:
        guard = PortGuard(DISPLAY_SPEC)
        guard.guard()  # DISPLAY_SPEC has no health_port -- always a no-op
