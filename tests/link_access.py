"""Test-only access to the parts of a ``DisplayLink`` a test must reach into.

Production hands the write seat away once and keeps generations behind opaque
references; a test that drives a link directly needs a writer on demand and, to
script a dial's socket, the generation behind its name. Both come from the link's
own private state, here and nowhere else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_link import DisplayLink
    from punt_lux.domain.hub.display_writer import DisplayWriter

__all__ = ["generation_of", "writer_of"]


def writer_of(link: DisplayLink) -> DisplayWriter:
    """A writer pinned to ``link``'s current dial, without taking the seat."""
    return link._desk._seat.current()  # test seam: production takes the seat once


def generation_of(link: DisplayLink) -> DialGeneration:
    """The generation behind ``link``'s current dial."""
    return link._connection.require()  # test seam: production holds only refs
