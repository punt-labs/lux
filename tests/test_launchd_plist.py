"""Installed configuration resolves home per instance and preserves IO errors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux._launchd_plist import LaunchdPlist
from punt_lux.service import HUB_SPEC


def test_plist_missing_write_and_read(tmp_path: Path) -> None:
    with patch("pathlib.Path.home", return_value=tmp_path):
        plist = LaunchdPlist(HUB_SPEC)
    assert (
        plist.path
        == tmp_path / "Library/LaunchAgents" / f"{HUB_SPEC.launchd_label}.plist"
    )
    assert plist.installed_content() == ""
    plist.write("<plist/>")
    assert plist.installed_content() == "<plist/>"
    assert plist.spec is HUB_SPEC
    with patch(
        "punt_lux._launchctl.LaunchctlSubsystem.gui_domain", return_value="gui/42"
    ):
        assert plist.target == f"gui/42/{HUB_SPEC.launchd_label}"


def test_plist_does_not_hide_read_errors() -> None:
    with (
        patch.object(Path, "read_text", side_effect=PermissionError("denied")),
        pytest.raises(PermissionError, match="denied"),
    ):
        LaunchdPlist(HUB_SPEC).installed_content()
