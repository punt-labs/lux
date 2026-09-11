"""WireRequire — shared wire-boundary isinstance-or-raise checks."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.wire_require import WireRequire


class TestList:
    def test_returns_a_valid_list(self) -> None:
        assert WireRequire.list_([1, 2], "nodes") == [1, 2]

    def test_rejects_a_non_list(self) -> None:
        with pytest.raises(ValueError, match="nodes must be a list of nodes"):
            WireRequire.list_("oops", "nodes")

    def test_names_the_offending_type(self) -> None:
        with pytest.raises(ValueError, match="got str"):
            WireRequire.list_("oops", "nodes")


class TestMapping:
    def test_returns_a_valid_mapping(self) -> None:
        assert WireRequire.mapping({"label": "a"}, "nodes[0]") == {"label": "a"}

    def test_rejects_a_non_mapping(self) -> None:
        with pytest.raises(ValueError, match="nodes\\[0\\] must be a mapping"):
            WireRequire.mapping(42, "nodes[0]")


class TestString:
    def test_returns_a_valid_string(self) -> None:
        assert WireRequire.string("a", "label is missing") == "a"

    def test_rejects_a_non_string(self) -> None:
        with pytest.raises(ValueError, match="label is missing"):
            WireRequire.string(42, "label is missing")

    def test_names_the_offending_value(self) -> None:
        with pytest.raises(ValueError, match="got 42"):
            WireRequire.string(42, "label is missing")
