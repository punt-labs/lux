"""SettleErrors -- the ways code can misuse a settler.

A rule the code broke, not a condition of the data, so a
:class:`~punt_lux.domain.programmer_error.ProgrammerError`.
"""

from __future__ import annotations

from typing import final

from punt_lux.domain.programmer_error import ProgrammerError

__all__ = ["UnendedDialError"]


@final
class UnendedDialError(ProgrammerError):
    """A dial no one ended, and no one asked to end, was settled."""
