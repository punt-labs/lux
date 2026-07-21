"""DisplayModeStore — the config-file boundary that maps I/O failure to fault."""

from __future__ import annotations

from pathlib import Path

from punt_lux.operations.display_mode_store import DisplayModeStore
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.config import DisplayModeState


def test_read_defaults_to_off_for_a_fresh_repo(tmp_path: Path) -> None:
    result = DisplayModeStore(str(tmp_path)).read()
    assert isinstance(result, DisplayModeState)
    assert result.mode == "off"


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    assert DisplayModeStore(str(tmp_path)).write("y") is None
    assert DisplayModeStore(str(tmp_path)).read() == DisplayModeState(mode="on")


def test_read_faults_when_the_config_file_is_unreadable(tmp_path: Path) -> None:
    # lux.md is a directory, so the read raises IsADirectoryError (an OSError):
    # the store maps it to a fault instead of letting it crash the operation.
    (tmp_path / ".punt-labs").mkdir()
    (tmp_path / ".punt-labs" / "lux.md").mkdir()
    result = DisplayModeStore(str(tmp_path)).read()
    assert isinstance(result, OpError)
    assert result.code == "fault"


def test_write_faults_when_the_config_path_is_unusable(tmp_path: Path) -> None:
    # .punt-labs is a file, so writing <repo>/.punt-labs/lux.md fails with an
    # OSError the store maps to a fault.
    (tmp_path / ".punt-labs").write_text("not a directory")
    result = DisplayModeStore(str(tmp_path)).write("y")
    assert isinstance(result, OpError)
    assert result.code == "fault"
