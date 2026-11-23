"""A live dial reference has an opaque stable token, distinct from other dials."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from punt_lux.hub.generation_ref import GenerationRef

if TYPE_CHECKING:
    from punt_lux.hub.dial_generation import DialGeneration


def test_token_stays_stable_and_does_not_reuse_an_object_address() -> None:
    first = GenerationRef(cast("DialGeneration", object()))
    second = GenerationRef(cast("DialGeneration", object()))
    assert str(first) == str(first)
    assert len(str(first)) == 32
    assert str(first) != str(second)


def test_references_to_the_same_generation_still_compare_and_hash_equally() -> None:
    generation = cast("DialGeneration", object())
    first, second = GenerationRef(generation), GenerationRef(generation)
    assert first == second
    assert hash(first) == hash(second)
    assert first != object()
