"""SelectionWire — the shared wire coercion table.py and tree.py's codecs share."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.selection_wire import SelectionWire


class TestDecodeMode:
    @pytest.mark.parametrize("mode", ["none", "single", "multi"])
    def test_accepts_every_valid_mode(self, mode: str) -> None:
        assert SelectionWire.decode_mode(mode) == mode

    def test_rejects_an_unknown_string(self) -> None:
        with pytest.raises(ValueError, match="selection_mode must be one of"):
            SelectionWire.decode_mode("bogus")

    @pytest.mark.parametrize("raw", [[], {}, 42, None])
    def test_rejects_unhashable_and_non_string_values_with_value_error(
        self, raw: object
    ) -> None:
        # A list/dict is unhashable; decode_mode must isinstance-check before
        # the frozenset membership test, or this raises TypeError instead.
        with pytest.raises(ValueError, match="selection_mode must be one of"):
            SelectionWire.decode_mode(raw)


class TestDecodeIds:
    def test_returns_the_list_of_strings(self) -> None:
        assert SelectionWire.decode_ids(["a", "b"], "selected_node_ids") == ["a", "b"]

    def test_rejects_a_non_list(self) -> None:
        with pytest.raises(ValueError, match="selected_node_ids must be a list"):
            SelectionWire.decode_ids("not-a-list", "selected_node_ids")

    def test_rejects_a_list_with_a_non_string_item(self) -> None:
        with pytest.raises(ValueError, match="selected_node_ids must be a list"):
            SelectionWire.decode_ids(["a", 1], "selected_node_ids")


class TestEmitFields:
    def test_none_mode_and_empty_selection_stays_terse(self) -> None:
        payload: dict[str, object] = {}
        SelectionWire.emit_fields(
            payload, mode="none", selected_ids=frozenset(), anchor_id="", noun="row"
        )
        assert payload == {}

    def test_writes_all_three_fields_when_set(self) -> None:
        payload: dict[str, object] = {}
        SelectionWire.emit_fields(
            payload,
            mode="multi",
            selected_ids=frozenset({"b", "a"}),
            anchor_id="a",
            noun="node",
        )
        assert payload == {
            "selection_mode": "multi",
            "selected_node_ids": ["a", "b"],
            "anchor_node_id": "a",
        }

    def test_noun_names_the_selectable_unit(self) -> None:
        payload: dict[str, object] = {}
        SelectionWire.emit_fields(
            payload,
            mode="single",
            selected_ids=frozenset({"r0"}),
            anchor_id="r0",
            noun="row",
        )
        assert "selected_row_ids" in payload
        assert "anchor_row_id" in payload
