"""Physical modifiers retain their terminal meaning on both platform mappings."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from punt_lux.display.terminal.keymap import terminal_mods


@pytest.mark.parametrize("mac", [False, True])
@pytest.mark.parametrize("mask", range(16))
def test_modifier_combinations(mask: int, mac: bool) -> None:
    shift, ctrl, alt, cmd = (bool(mask & bit) for bit in (1, 2, 4, 8))
    io = SimpleNamespace(
        config_mac_osx_behaviors=mac,
        key_shift=shift,
        key_ctrl=cmd if mac else ctrl,
        key_alt=alt,
        key_super=ctrl if mac else cmd,
    )
    with patch("punt_lux.display.terminal.keymap.imgui.get_io", return_value=io):
        assert terminal_mods() == mask
