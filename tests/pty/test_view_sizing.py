"""An observer does not fight the active viewer's authoritative resize."""

from __future__ import annotations

from punt_lux.display.terminal.sizing import ViewSizing


def test_repaint_preserves_requested_geometry_and_does_not_pingpong() -> None:
    sizing = ViewSizing((80, 24))
    sizing.adopt((80, 24))
    assert sizing.fit((100, 30)) == "remote"
    sizing.adopt((40, 8))  # another viewer became active
    assert sizing.actual == (40, 8)
    assert sizing.fit((100, 30)) == "none"
    assert sizing.fit((120, 40)) == "remote"  # this window actually changed


def test_local_and_fixed_size_modes() -> None:
    local = ViewSizing((80, 24))
    assert local.fit((100, 30)) == "local"
    assert local.actual == (100, 30)
    local.fixed = True
    assert local.fit((120, 40)) == "none"
    assert local.actual == (100, 30)
