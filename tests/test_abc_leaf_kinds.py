"""Tests for ``DefaultLeafKinds`` — the leaf-path spec assembler.

The leaf builder owns the spec for every migrated kind decoded without child
recursion (the static display leaves, the Dialog composite-that-decodes-as-a-leaf,
and the interactive value inputs). These tests pin that every spec it yields is a
leaf and that the set matches the import-light name registry, so the split from
the registry aggregator cannot silently drop or mis-flag a kind.
"""

from __future__ import annotations

from punt_lux.protocol.elements.abc_kind_names import AbcKindNames
from punt_lux.protocol.elements.abc_leaf_kinds import DefaultLeafKinds


class TestDefaultLeafKinds:
    """The leaf builder yields exactly the non-container migrated kinds."""

    def test_every_spec_is_a_leaf(self) -> None:
        assert all(not spec.is_container for spec in DefaultLeafKinds.specs())

    def test_kinds_are_the_migrated_non_container_kinds(self) -> None:
        kinds = {spec.kind for spec in DefaultLeafKinds.specs()}
        expected = AbcKindNames.MIGRATED_ABC_KINDS - AbcKindNames.ABC_CONTAINER_KINDS
        assert kinds == expected

    def test_no_duplicate_kinds(self) -> None:
        specs = DefaultLeafKinds.specs()
        assert len({spec.kind for spec in specs}) == len(specs)

    def test_dialog_is_present_as_a_leaf(self) -> None:
        by_kind = {spec.kind: spec for spec in DefaultLeafKinds.specs()}
        assert "dialog" in by_kind
        assert not by_kind["dialog"].is_container
