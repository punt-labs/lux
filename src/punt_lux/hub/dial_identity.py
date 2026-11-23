"""The capability and wire name identifying one Hub dial."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from itertools import count
from typing import TYPE_CHECKING, Self

from punt_lux.hub.generation_ref import GenerationRef

if TYPE_CHECKING:
    from punt_lux.hub.dial_generation import DialGeneration

_HUB_STARTED = time.time_ns()
_DIAL_SEQUENCE = count(1)


@dataclass(frozen=True, slots=True)
class DialIdentity:
    """Two names for the same dial, kept for its entire lifetime."""

    reference: GenerationRef
    name: str

    @classmethod
    def for_generation(cls, generation: DialGeneration) -> Self:
        """Allocate a per-process sequence name and the dial's capability."""
        return cls(
            reference=GenerationRef(generation),
            name=f"{os.getpid()}:{_HUB_STARTED}:{next(_DIAL_SEQUENCE)}",
        )
