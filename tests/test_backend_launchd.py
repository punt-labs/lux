"""Tests for punt_lux._backend_launchd -- launchd install() idempotency (lux-94p0)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from punt_lux._backend_launchd import LaunchdBackend
from punt_lux.service import HUB_SPEC


def _result(returncode: int):
    class _Result:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    return _Result()


class TestLaunchdInstallIdempotency:
    """install() must not bootout a live daemon when nothing would change.

    The bootout-then-bootstrap path only belongs on a genuine content
    change. A daemon serving live long-lived MCP connections may never
    actually die on SIGTERM (uvicorn's default graceful-shutdown window is
    unbounded), so reinstalling an already-correct, already-active service
    must return without touching launchd at all.
    """

    def test_install_is_a_noop_when_active_with_matching_plist(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "luxd-hub").touch()

        with (
            patch("punt_lux._backend_launchd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
            patch("punt_lux.hub_paths.Path.home", return_value=fake_home),
            patch("punt_lux._launchctl.subprocess.run") as run,
        ):
            backend = LaunchdBackend(HUB_SPEC)
            # First install: not yet active, writes the plist the normal way.
            with patch.object(backend, "is_active", return_value=False):
                run.return_value = _result(0)  # bootstrap -> succeeds
                first_result = backend.install()
            assert first_result is False
            run.reset_mock()

            # Second install, same binary path, now active: nothing changed,
            # so a live daemon must never be booted out for this reinstall.
            with patch.object(backend, "is_active", return_value=True):
                second_result = backend.install()

        assert second_result is True
        run.assert_not_called()

    def test_install_still_cures_when_plist_content_differs(self, tmp_path: Path):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "luxd-hub").touch()

        with (
            patch("punt_lux._backend_launchd.Path.home", return_value=fake_home),
            patch("punt_lux._service_spec.Path.home", return_value=fake_home),
            patch("punt_lux.hub_paths.Path.home", return_value=fake_home),
            patch("punt_lux._launchctl.subprocess.run") as run,
        ):
            backend = LaunchdBackend(HUB_SPEC)
            backend.config_path().parent.mkdir(parents=True, exist_ok=True)
            backend.config_path().write_text("<stale plist content>")

            with patch.object(backend, "is_active", return_value=True):
                run.side_effect = [
                    _result(0),  # print -> registered
                    _result(0),  # bootout -> succeeds
                    _result(1),  # print -> gone
                    _result(0),  # bootstrap -> succeeds
                ]
                result = backend.install()

        assert result is False
        verbs_issued = [call.args[0] for call in run.call_args_list]
        assert any(v[:2] == ["launchctl", "bootout"] for v in verbs_issued)
        assert any(v[:2] == ["launchctl", "bootstrap"] for v in verbs_issued)
