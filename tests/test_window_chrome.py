"""Tests for the window chrome value objects — placement and flags.

Each maps flat wire fields onto a cohesive value object and back. These pin the
default-filling, the off-flag omission, and the active-name ordering the display
adapter folds into an ImGui mask.
"""

from __future__ import annotations

from punt_lux.protocol.elements.window_chrome import WindowFlags, WindowPlacement


class TestWindowPlacement:
    def test_defaults(self) -> None:
        assert WindowPlacement() == WindowPlacement(
            x=50.0, y=50.0, width=300.0, height=200.0
        )

    def test_from_wire_reads_present_values(self) -> None:
        placement = WindowPlacement.from_wire(
            {"x": 10, "y": 20, "width": 400, "height": 300}
        )
        assert placement == WindowPlacement(x=10, y=20, width=400, height=300)

    def test_from_wire_defaults_absent_scalars(self) -> None:
        placement = WindowPlacement.from_wire({"x": 5})
        assert placement == WindowPlacement(x=5, y=50.0, width=300.0, height=200.0)

    def test_to_wire_round_trips(self) -> None:
        placement = WindowPlacement(x=1, y=2, width=3, height=4)
        assert WindowPlacement.from_wire(placement.to_wire()) == placement


class TestWindowFlags:
    def test_defaults_are_all_off(self) -> None:
        assert WindowFlags().active_names() == ()

    def test_from_wire_reads_set_flags(self) -> None:
        flags = WindowFlags.from_wire({"no_move": True, "auto_resize": True})
        assert flags.no_move is True
        assert flags.auto_resize is True
        assert flags.no_resize is False

    def test_to_wire_omits_off_flags(self) -> None:
        wire = WindowFlags(no_move=True).to_wire()
        assert wire == {"no_move": True}

    def test_active_names_are_in_wire_order(self) -> None:
        flags = WindowFlags(no_resize=True, no_move=True, auto_resize=True)
        assert flags.active_names() == ("no_move", "no_resize", "auto_resize")

    def test_from_wire_to_wire_round_trips(self) -> None:
        flags = WindowFlags(no_collapse=True, no_scrollbar=True)
        assert WindowFlags.from_wire(flags.to_wire()) == flags
