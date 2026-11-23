"""A dial's immutable identity owns its capability and process-scoped name."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from itertools import count
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest

from punt_lux.hub.dial_identity import DialIdentity
from punt_lux.hub.generation_ref import GenerationRef

if TYPE_CHECKING:
    from punt_lux.hub.dial_generation import DialGeneration


def test_identity_binds_the_capability_to_a_nonempty_sequence_name() -> None:
    generation = cast("DialGeneration", object())
    with (
        patch("punt_lux.hub.dial_identity.os.getpid", return_value=100),
        patch("punt_lux.hub.dial_identity._HUB_STARTED", 200),
        patch("punt_lux.hub.dial_identity._DIAL_SEQUENCE", count(1)),
    ):
        first = DialIdentity.for_generation(generation)
        second = DialIdentity.for_generation(cast("DialGeneration", object()))
    assert first.reference == GenerationRef(generation)
    assert first.name == "100:200:1"
    assert second.name == "100:200:2"
    assert first.reference != second.reference


def test_identity_cannot_lose_its_name_after_publication() -> None:
    identity = DialIdentity.for_generation(cast("DialGeneration", object()))
    with pytest.raises(FrozenInstanceError):
        identity.__setattr__("name", "")
