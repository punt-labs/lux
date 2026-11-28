"""DisplayModeStore — the config-file boundary that maps I/O failure to fault."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from punt_lux.service.display_mode_store import DisplayModeStore
from punt_lux.wire.operations.common import OpError
from punt_lux.wire.operations.config import DisplayModeState


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git = shutil.which("git") or "/usr/bin/git"
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".punt-labs/local/\n")
    return tmp_path


def test_read_defaults_to_off_for_a_fresh_repo(repo: Path) -> None:
    result = DisplayModeStore(str(repo)).read()
    assert isinstance(result, DisplayModeState)
    assert result.mode == "off"


def test_write_then_read_round_trips(repo: Path) -> None:
    assert DisplayModeStore(str(repo)).write("y") is None
    assert DisplayModeStore(str(repo)).read() == DisplayModeState(mode="on")


def test_read_faults_when_the_config_file_is_unreadable(repo: Path) -> None:
    # lux.md is a directory, so the read raises IsADirectoryError (an OSError):
    # the store maps it to a fault instead of letting it crash the operation.
    (repo / ".punt-labs").mkdir()
    (repo / ".punt-labs" / "lux.md").mkdir()
    result = DisplayModeStore(str(repo)).read()
    assert isinstance(result, OpError)
    assert result.code == "fault"


def test_write_faults_when_the_config_path_is_unusable(repo: Path) -> None:
    # .punt-labs is a file, so the store cannot write the local preference.
    (repo / ".punt-labs").write_text("not a directory")
    result = DisplayModeStore(str(repo)).write("y")
    assert isinstance(result, OpError)
    assert result.code == "fault"
