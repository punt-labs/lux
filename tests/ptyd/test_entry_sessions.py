"""Each spawned Python entry detaches before constructing its application."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from punt_lux.ptyd.__main__ import PtyEntryPoint
from punt_lux.ptyd.menu_entry import MenuEntryPoint

if TYPE_CHECKING:
    from pathlib import Path


class ReachedStartupError(Exception):
    pass


@pytest.mark.parametrize(
    ("entry", "startup"),
    [
        (PtyEntryPoint, "punt_lux.ptyd.__main__.argparse.ArgumentParser"),
        (MenuEntryPoint, "punt_lux.ptyd.menu_entry.MenuEntryPoint.serve"),
    ],
)
@pytest.mark.parametrize("already_detached", [False, True])
@pytest.mark.parametrize("group_leader", [False, True])
def test_entry_detaches_before_startup(
    entry: type[PtyEntryPoint] | type[MenuEntryPoint],
    startup: str,
    already_detached: bool,
    group_leader: bool,
) -> None:
    with (
        patch("os.getpid", return_value=100),
        patch("os.getsid", return_value=100 if already_detached else 99),
        patch(
            "os.setsid", side_effect=PermissionError if group_leader else None
        ) as detach,
        patch("sys.argv", ["entry", "42"]),
        patch(startup, side_effect=ReachedStartupError),
        pytest.raises(ReachedStartupError),
    ):
        entry.main()
    assert detach.call_count == (0 if already_detached else 1)


@pytest.mark.parametrize("entry", [PtyEntryPoint, MenuEntryPoint])
def test_entry_does_not_ignore_a_detachment_failure(
    entry: type[PtyEntryPoint] | type[MenuEntryPoint],
) -> None:
    with (
        patch("os.getpid", return_value=100),
        patch("os.getsid", return_value=99),
        patch("os.setsid", side_effect=OSError("detachment failed")),
        pytest.raises(OSError, match="detachment failed"),
    ):
        entry.main()


def test_foreground_process_group_leader_can_show_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "punt_lux.ptyd", "--help"],
        process_group=0,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Lux local terminal-session owner" in result.stdout


def test_detached_terminal_daemon_logs_a_run_loop_failure(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from types import SimpleNamespace\n"
                "from unittest.mock import patch\n"
                "from punt_lux.ptyd import __main__ as entry\n"
                "def run():\n"
                "    raise RuntimeError('private terminal content')\n"
                "application = SimpleNamespace(run=run, stop=lambda: None)\n"
                "module = SimpleNamespace(PtyApplication=lambda *a, **k: application)\n"
                "with patch.object(entry, 'import_module', return_value=module):\n"
                "    entry.PtyEntryPoint.main()\n"
            ),
        ],
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        env={**os.environ, "HOME": str(tmp_path), "LUX_LOG_LEVEL": "INFO"},
    )
    assert result.returncode == 1
    log = (tmp_path / ".punt-labs/lux/logs/lux.log").read_text()
    assert "terminal daemon failed: RuntimeError" in log
    assert "run:5" in log
    assert "private terminal content" not in log
