"""Installed hook commands keep the context stream free of diagnostics."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from punt_lux.__main__ import app
from punt_lux.service.applet_event import AppletEvent


@pytest.mark.parametrize("event", list(AppletEvent))
def test_event_command_stdout_is_empty(tmp_path: Path, event: AppletEvent) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "punt_lux", "hook", "applet-event", event.value],
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""


@pytest.mark.parametrize(
    "args",
    [[], ["/private/alice"], ["launched", "--child-pid", "-1"]],
)
def test_invalid_events_are_rejected(args: list[str]) -> None:
    result = CliRunner().invoke(app, ["hook", "applet-event", *args])
    assert result.exit_code == 2
