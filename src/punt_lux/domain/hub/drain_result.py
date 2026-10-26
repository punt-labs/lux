"""DrainResult -- what the last look at a dial's socket found, or why there was none."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DrainIncompleteError", "Drained"]


class DrainIncompleteError(Exception):
    """The last look could not be made: a writer held the socket past its ceiling."""


@dataclass(frozen=True, slots=True)
class Drained:
    """What one last look at a socket found: bytes, whether its stream ended."""

    chunk: bytes
    ended: bool
