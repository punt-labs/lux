"""A dial reference is an identity-only name with no transport token."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from punt_lux.hub.generation_ref import GenerationRef

if TYPE_CHECKING:
    from punt_lux.hub.dial_generation import DialGeneration


def test_references_to_the_same_generation_still_compare_and_hash_equally() -> None:
    generation = cast("DialGeneration", object())
    first, second = GenerationRef(generation), GenerationRef(generation)
    assert first == second
    assert hash(first) == hash(second)
    assert first != object()
