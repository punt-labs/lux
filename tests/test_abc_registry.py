"""Tests for the ABC-kind registry and its cross-check against ``AbcKindNames``.

The registry is the single source of truth for which kinds decode/encode onto
the Element ABC. ``AbcKindNames`` holds the same fact as import-light strings
for the container gate; ``DefaultAbcKinds.verify_names`` is the fail-loud guard
that keeps the two data homes in agreement. These tests pin the registry's
contract and prove the guard catches drift.
"""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.abc_kind_names import AbcKindNames
from punt_lux.protocol.elements.abc_kind_spec import KindCodec
from punt_lux.protocol.elements.abc_kind_specs import ContainerKindSpec, LeafKindSpec
from punt_lux.protocol.elements.abc_kind_table import (
    DEFAULT_ABC_REGISTRY,
    DefaultAbcKinds,
)
from punt_lux.protocol.elements.abc_registry import AbcElementRegistry


def _no_encode(_elem: object) -> dict[str, object]:
    """A stand-in encoder — the name cross-check never invokes it."""
    return {}


def _dummy_codec() -> KindCodec:
    """A codec whose classes are never invoked by the name cross-check."""
    return KindCodec(
        element_cls=type("Dummy", (), {}),
        decoder_cls=object,
        encoder=_no_encode,
    )


def _full_registry(*, group_as_leaf: bool) -> AbcElementRegistry:
    """Build a registry covering every migrated kind.

    With ``group_as_leaf`` the ``group`` container is mis-registered as a leaf,
    so ``all_kinds`` still matches the names but ``container_kinds`` does not.
    """
    registry = AbcElementRegistry()
    for kind in AbcKindNames.MIGRATED_ABC_KINDS:
        as_container = kind in AbcKindNames.ABC_CONTAINER_KINDS and not (
            group_as_leaf and kind == "group"
        )
        if as_container:
            registry.register(ContainerKindSpec(kind=kind, codec=_dummy_codec()))
        else:
            registry.register(LeafKindSpec(kind=kind, codec=_dummy_codec()))
    return registry


class TestDefaultRegistryContract:
    """The production registry's derived views."""

    def test_all_kinds_match_names(self) -> None:
        assert DEFAULT_ABC_REGISTRY.all_kinds == AbcKindNames.MIGRATED_ABC_KINDS

    def test_container_kinds_match_names(self) -> None:
        assert DEFAULT_ABC_REGISTRY.container_kinds == AbcKindNames.ABC_CONTAINER_KINDS

    def test_leaf_and_container_partition_all_kinds(self) -> None:
        registry = DEFAULT_ABC_REGISTRY
        assert registry.leaf_kinds | registry.container_kinds == registry.all_kinds
        assert not (registry.leaf_kinds & registry.container_kinds)

    def test_abc_types_one_per_kind(self) -> None:
        registry = DEFAULT_ABC_REGISTRY
        assert len(registry.abc_types) == len(registry.all_kinds)

    def test_dialog_is_a_leaf(self) -> None:
        # Dialog decodes its child Buttons itself, so it dispatches on the leaf
        # path even though it holds children.
        assert "dialog" in DEFAULT_ABC_REGISTRY.leaf_kinds
        assert "dialog" not in DEFAULT_ABC_REGISTRY.container_kinds


class TestDuplicateRegistration:
    """A kind registers exactly once."""

    def test_duplicate_kind_raises(self) -> None:
        registry = AbcElementRegistry()
        registry.register(LeafKindSpec(kind="text", codec=_dummy_codec()))
        with pytest.raises(ValueError, match="Duplicate ABC kind registration"):
            registry.register(LeafKindSpec(kind="text", codec=_dummy_codec()))


class TestNameCrossCheck:
    """``verify_names`` is the fail-loud guard between the two data homes."""

    def test_default_registry_agrees_with_names(self) -> None:
        # The production build passed this at import; assert it explicitly.
        DefaultAbcKinds.verify_names(_full_registry(group_as_leaf=False))

    def test_spec_without_a_name_raises(self) -> None:
        registry = AbcElementRegistry()
        registry.register(LeafKindSpec(kind="widget", codec=_dummy_codec()))
        with pytest.raises(RuntimeError, match="disagree on migrated kinds"):
            DefaultAbcKinds.verify_names(registry)

    def test_container_mis_registered_as_leaf_raises(self) -> None:
        # ``all_kinds`` matches, but a container declared as a leaf is caught by
        # the second half of the guard.
        with pytest.raises(RuntimeError, match="disagree on container kinds"):
            DefaultAbcKinds.verify_names(_full_registry(group_as_leaf=True))
