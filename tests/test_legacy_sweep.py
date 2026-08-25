"""Tests for LaunchdLegacySweep / SystemdLegacySweep -- the cure/verify primitive.

Regression coverage for lux-ehzy: ``launchctl unload -w`` no-ops on a
``bootstrap``-registered service, and the plist was deleted regardless
(docs/architecture/service-lifecycle-migration.md §1, §7). These tests patch
the actual call site (``punt_lux._launchctl.subprocess.run`` /
``punt_lux._legacy_sweep_systemd.subprocess.run``), never a module-level
``subprocess`` re-import, per the existing pattern in test_service.py's
``TestBackendStartStopSymmetry``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux._legacy_sweep_launchd import LaunchdLegacySweep
from punt_lux._legacy_sweep_systemd import SystemdLegacySweep
from punt_lux._service_errors import ServiceMigrationError
from punt_lux.service import HUB_SPEC


def _spec_with_labels(*labels: str):
    return replace(HUB_SPEC, legacy_launchd_labels=labels)


def _spec_with_units(*units: str):
    return replace(HUB_SPEC, legacy_systemd_units=units)


class TestLaunchdLegacySweepVerbs:
    def test_sweep_uses_bootout_and_print_never_unload(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._legacy_sweep_launchd.Path.home", return_value=fake_home):
            sweep = LaunchdLegacySweep(_spec_with_labels("com.punt-labs.lux"))

        with patch("punt_lux._launchctl.subprocess.run") as run:
            # First print (pre-check): registered. bootout: succeeds. Second
            # print (post-check): now gone.
            run.side_effect = [
                _result(0),  # print -> found (not clean)
                _result(0),  # bootout -> succeeds
                _result(1),  # print -> gone (clean)
            ]
            report = sweep.sweep()

        assert report.all_clean
        verbs_issued = [call.args[0] for call in run.call_args_list]
        assert any(v[:2] == ["launchctl", "print"] for v in verbs_issued)
        assert any(v[:2] == ["launchctl", "bootout"] for v in verbs_issued)
        assert not any("unload" in v for v in verbs_issued)
        assert not any("load" in v and "unload" not in v for v in verbs_issued)

    def test_sweep_no_ops_when_already_clean(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._legacy_sweep_launchd.Path.home", return_value=fake_home):
            sweep = LaunchdLegacySweep(_spec_with_labels("com.punt-labs.lux"))

        with patch("punt_lux._launchctl.subprocess.run") as run:
            run.return_value = _result(1)  # print -> not found -> already clean
            report = sweep.sweep()

        assert report.all_clean
        # is_clean() short-circuits sweep()'s per-identifier work: only the
        # single read-only print call, never bootout.
        verbs_issued = [call.args[0][:2] for call in run.call_args_list]
        assert ["launchctl", "bootout"] not in verbs_issued


class TestLaunchdLegacySweepOrderingFidelity:
    """Fidelity control -- reproduces the exact §1 bug if the ordering fix regresses."""

    def test_config_file_survives_a_lying_deregister(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        agents = fake_home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        plist = agents / "com.punt-labs.lux.plist"
        plist.write_text("<plist/>")

        with patch("punt_lux._legacy_sweep_launchd.Path.home", return_value=fake_home):
            sweep = LaunchdLegacySweep(_spec_with_labels("com.punt-labs.lux"))

        with patch("punt_lux._launchctl.subprocess.run") as run:
            # print always reports "found" -- before AND after bootout --
            # simulating a supervisor call that silently failed to
            # deregister (the exact cross-domain no-op the operator hit).
            run.return_value = _result(0)
            with pytest.raises(ServiceMigrationError, match=r"com\.punt-labs\.lux"):
                sweep.sweep()

        # The ordering fix: no file deletion without confirmed deregistration.
        assert plist.exists()


class TestLaunchdLegacySweepNonShortCircuit:
    def test_every_identifier_is_attempted_and_both_failures_are_named(
        self, tmp_path: Path
    ):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with patch("punt_lux._legacy_sweep_launchd.Path.home", return_value=fake_home):
            sweep = LaunchdLegacySweep(
                _spec_with_labels("com.punt-labs.lux-a", "com.punt-labs.lux-b")
            )

        with patch("punt_lux._launchctl.subprocess.run") as run:
            # Both labels: print says "found" always (never clean, bootout
            # never resolves it) -- both must be attempted, both must be
            # named in the raised error.
            run.return_value = _result(0)
            with pytest.raises(ServiceMigrationError) as exc_info:
                sweep.sweep()

        message = str(exc_info.value)
        assert "com.punt-labs.lux-a" in message
        assert "com.punt-labs.lux-b" in message
        # Each identifier: one pre-check print, one bootout, one post-check
        # print = 3 calls; two identifiers = 6 calls minimum -- proves the
        # second identifier was reached, not skipped after the first failure.
        assert run.call_count >= 6


class TestLaunchdLegacySweepDiagnose:
    def test_diagnose_never_mutates(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        agents = fake_home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        plist = agents / "com.punt-labs.lux.plist"
        plist.write_text("<plist/>")

        with patch("punt_lux._legacy_sweep_launchd.Path.home", return_value=fake_home):
            sweep = LaunchdLegacySweep(_spec_with_labels("com.punt-labs.lux"))

        with patch("punt_lux._launchctl.subprocess.run") as run:
            run.return_value = _result(0)  # registered
            report = sweep.diagnose()

        assert not report.all_clean
        verbs_issued = [call.args[0][:2] for call in run.call_args_list]
        assert ["launchctl", "bootout"] not in verbs_issued
        assert plist.exists()


class TestSystemdLegacySweepVerbs:
    def test_sweep_uses_is_active_disable_and_daemon_reload_never_unload(
        self, tmp_path: Path
    ):
        fake_home = tmp_path / "home"
        units = fake_home / ".config" / "systemd" / "user"
        units.mkdir(parents=True)
        unit_file = units / "lux.service"
        unit_file.write_text("[Unit]")

        with patch("punt_lux._legacy_sweep_systemd.Path.home", return_value=fake_home):
            sweep = SystemdLegacySweep(_spec_with_units("lux"))

        with patch("punt_lux._legacy_sweep_systemd.subprocess.run") as run:
            run.side_effect = [
                _result(0),  # is-active -> active (not clean)
                _result(0),  # disable --now -> succeeds
                _result(3),  # is-active -> inactive (safe to remove)
                _result(0),  # daemon-reload -> succeeds
            ]
            report = sweep.sweep()

        assert report.all_clean
        assert not unit_file.exists()
        verbs_issued = [call.args[0] for call in run.call_args_list]
        assert any(v[:3] == ["systemctl", "--user", "is-active"] for v in verbs_issued)
        assert any(
            v[:4] == ["systemctl", "--user", "disable", "--now"] for v in verbs_issued
        )
        assert any(
            v[:3] == ["systemctl", "--user", "daemon-reload"] for v in verbs_issued
        )
        assert not any("unload" in v for v in verbs_issued)


class TestSystemdLegacySweepOrderingFidelity:
    def test_config_file_survives_a_lying_disable(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        units = fake_home / ".config" / "systemd" / "user"
        units.mkdir(parents=True)
        unit_file = units / "lux.service"
        unit_file.write_text("[Unit]")

        with patch("punt_lux._legacy_sweep_systemd.Path.home", return_value=fake_home):
            sweep = SystemdLegacySweep(_spec_with_units("lux"))

        with patch("punt_lux._legacy_sweep_systemd.subprocess.run") as run:
            # ``is-active`` always reports "active" -- the unit is still
            # running, so the file must survive to keep systemd able to stop it.
            run.return_value = _result(0)
            with pytest.raises(ServiceMigrationError, match="lux"):
                sweep.sweep()

        assert unit_file.exists()

    def test_disabled_inactive_unit_with_stale_file_is_swept_clean(
        self, tmp_path: Path
    ):
        """A unit already disabled+inactive but whose .service file is on disk
        must be cleared. Regression for the Ubuntu install-path failure where
        the legacy ``lux.service`` blocked ``luxd-hub`` registration in a loop
        the caller could not break with any obvious workaround.
        """
        fake_home = tmp_path / "home"
        units = fake_home / ".config" / "systemd" / "user"
        units.mkdir(parents=True)
        unit_file = units / "lux.service"
        unit_file.write_text("[Unit]")

        with patch("punt_lux._legacy_sweep_systemd.Path.home", return_value=fake_home):
            sweep = SystemdLegacySweep(_spec_with_units("lux"))

        with patch("punt_lux._legacy_sweep_systemd.subprocess.run") as run:
            run.side_effect = [
                _result(3),  # is-active -> inactive (file present -> not clean)
                _result(0),  # disable --now -> idempotent success
                _result(3),  # is-active -> still inactive (safe)
                _result(0),  # daemon-reload -> succeeds
            ]
            report = sweep.sweep()

        assert report.all_clean
        assert not unit_file.exists()


class _Result:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def _result(returncode: int) -> _Result:
    return _Result(returncode)
