"""Tests for the ABC-kind registry, its verifier, and the spec contract.

``AbcElementRegistry`` is the authoritative store of which kinds decode/encode
onto the Element ABC. ``AbcKindNames`` holds the same fact as import-light
strings for the container gate; ``AbcKindVerifier`` is the fail-loud guard that
keeps the two data homes in agreement AND that every interactive kind actually
wires its handler capability. These tests pin the contract and prove the guard
catches both name drift and a missing capability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from punt_lux.protocol.elements.abc_kind_codec import KindCodec
from punt_lux.protocol.elements.abc_kind_names import AbcKindNames
from punt_lux.protocol.elements.abc_kind_specs import (
    ContainerKindSpec,
    DialogKindSpec,
)
from punt_lux.protocol.elements.abc_kind_table import (
    DEFAULT_ABC_REGISTRY,
)
from punt_lux.protocol.elements.abc_kind_verify import AbcKindVerifier
from punt_lux.protocol.elements.abc_leaf_spec import LeafKindSpec
from punt_lux.protocol.elements.abc_registry import AbcElementRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.protocol.elements.abc_kind_spec import AbcKindSpec
    from punt_lux.protocol.handler_decoder import HandlerDecoder


def _no_encode(_elem: object) -> dict[str, object]:
    """A stand-in encoder — the verifier never invokes it."""
    return {}


def _dummy_codec() -> KindCodec:
    """A codec whose classes are never invoked by the verifier."""
    return KindCodec(
        element_cls=type("Dummy", (), {}), decoder_cls=object, encoder=_no_encode
    )


def _identity_pre_decode(raw: Mapping[str, object]) -> Mapping[str, object]:
    """A pre-decode marker — presence is all the verifier reads."""
    return raw


def _unused_handler_builder(_sink: PublishSink) -> HandlerDecoder[Any]:
    """Presence marks a spec handler-wired; the verifier never invokes it."""
    raise AssertionError("handler builder must not be called in verification")


def _leaf(kind: str, *, handler: bool = False, sugar: bool = False) -> LeafKindSpec:
    """Build a leaf spec, optionally handler-wired and/or sugar-canonicalizing."""
    return LeafKindSpec(
        kind=kind,
        codec=_dummy_codec(),
        handler_builder=_unused_handler_builder if handler else None,
        pre_decode=_identity_pre_decode if sugar else None,
    )


def _container(kind: str, *, handler: bool = False) -> ContainerKindSpec:
    """Build a container spec, optionally handler-wired."""
    return ContainerKindSpec(
        kind=kind,
        codec=_dummy_codec(),
        handler_builder=_unused_handler_builder if handler else None,
    )


def _full_specs() -> list[AbcKindSpec]:
    """Every migrated kind as a correctly-wired spec over dummy codecs."""
    return [
        _leaf("text"),
        _leaf("progress"),
        DialogKindSpec(codec=_dummy_codec()),
        _leaf("button", handler=True, sugar=True),
        _leaf("checkbox", handler=True),
        _leaf("input_text", handler=True),
        _leaf("input_number", handler=True),
        _leaf("slider", handler=True),
        _leaf("color_picker", handler=True),
        _leaf("combo", handler=True),
        _leaf("radio", handler=True),
        _container("group"),
        _container("collapsing_header", handler=True),
        _container("tab_bar", handler=True),
    ]


def _with_button(button: LeafKindSpec) -> list[AbcKindSpec]:
    """Return the full spec list with ``button`` swapped in."""
    return [button if spec.kind == "button" else spec for spec in _full_specs()]


def _registry(specs: list[AbcKindSpec]) -> AbcElementRegistry:
    """Register ``specs`` into a fresh registry for verification."""
    registry = AbcElementRegistry()
    for spec in specs:
        registry.register(spec)
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


class TestRegisterGuards:
    """``register`` rejects non-specs and duplicate kinds."""

    def test_duplicate_kind_raises(self) -> None:
        registry = AbcElementRegistry()
        registry.register(_leaf("text"))
        with pytest.raises(ValueError, match="Duplicate ABC kind registration"):
            registry.register(_leaf("text"))

    def test_non_spec_raises(self) -> None:
        registry = AbcElementRegistry()
        with pytest.raises(TypeError, match="not an AbcKindSpec"):
            registry.register(cast("AbcKindSpec", object()))


class TestKindCodec:
    """``KindCodec`` owns the encode call the three specs delegate to."""

    def test_encode_delegates_to_encoder(self) -> None:
        codec = KindCodec(element_cls=object, decoder_cls=object, encoder=_no_encode)
        assert codec.encode(object()) == {}


class TestNameParity:
    """``AbcKindVerifier`` fails loud when the specs disagree with the names."""

    def test_full_specs_verify_clean(self) -> None:
        AbcKindVerifier.verify(_registry(_full_specs()))

    def test_extra_kind_raises(self) -> None:
        specs: list[AbcKindSpec] = [*_full_specs(), _leaf("widget")]
        with pytest.raises(RuntimeError, match="disagree on migrated kinds"):
            AbcKindVerifier.verify(_registry(specs))

    def test_container_mis_flagged_as_leaf_raises(self) -> None:
        specs: list[AbcKindSpec] = [s for s in _full_specs() if s.kind != "group"]
        specs.append(_leaf("group"))
        with pytest.raises(RuntimeError, match="disagree on container kinds"):
            AbcKindVerifier.verify(_registry(specs))


class TestCapabilityParity:
    """Every interactive kind must wire handlers; Button must canonicalize sugar."""

    def test_interactive_kind_without_handler_raises(self) -> None:
        specs = _with_button(_leaf("button", sugar=True))
        with pytest.raises(RuntimeError, match="'handlers' capability"):
            AbcKindVerifier.verify(_registry(specs))

    def test_button_without_pre_decode_raises(self) -> None:
        specs = _with_button(_leaf("button", handler=True))
        with pytest.raises(RuntimeError, match="'pre_decode' capability"):
            AbcKindVerifier.verify(_registry(specs))
