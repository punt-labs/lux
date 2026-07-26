"""TableFlags — wire roundtrip and unknown-flag rejection."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.table_flags import TableFlags


class TestToWire:
    def test_defaults_emit_borders_and_row_bg(self) -> None:
        assert TableFlags().to_wire() == ["borders", "row_bg"]

    def test_all_flags_emit_in_canonical_order(self) -> None:
        flags = TableFlags(
            borders=True, row_bg=True, resizable=True, sortable=True, copy_id=True
        )
        assert flags.to_wire() == [
            "borders",
            "row_bg",
            "resizable",
            "sortable",
            "copy_id",
        ]

    def test_empty_flags_emit_nothing(self) -> None:
        assert TableFlags(borders=False, row_bg=False).to_wire() == []


class TestFromWire:
    def test_roundtrips_through_the_wire_form(self) -> None:
        flags = TableFlags(borders=True, sortable=True, row_bg=False)
        assert TableFlags.from_wire(flags.to_wire()) == flags

    def test_unset_names_default_off(self) -> None:
        flags = TableFlags.from_wire(["sortable"])
        assert flags == TableFlags(
            borders=False, row_bg=False, resizable=False, sortable=True, copy_id=False
        )

    def test_unknown_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown table flag"):
            TableFlags.from_wire(["borders", "striped"])
