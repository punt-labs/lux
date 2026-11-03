"""InvalidDrainError -- a look said to have found two things that cannot be."""

from __future__ import annotations

from typing import final

from punt_lux.domain.programmer_error import ProgrammerError

__all__ = ["InvalidDrainError"]


@final
class InvalidDrainError(ProgrammerError):
    """A look was said to have found bytes and the stream's end at once."""
