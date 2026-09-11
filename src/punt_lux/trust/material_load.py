"""MaterialLoad — wrap a load failure with directory context.

A save interrupted mid-write leaves a damaged or partial file; loading it
back raises ``cryptography``'s bare deserialization error, with no
indication of which directory or files caused it. This re-wraps that
failure into a message naming the directory, so the caller gets a clear,
actionable error instead of a "silent break."
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["MaterialLoad"]

_T = TypeVar("_T")


class MaterialLoad:
    """Namespace for wrapping a load failure with directory context."""

    @staticmethod
    def or_raise_clearly(directory: Path, load: Callable[[], _T]) -> _T:
        """Call *load*, or raise :class:`ValueError` naming *directory*
        if *load* itself raises :class:`ValueError` (damaged material).
        """
        try:
            return load()
        except ValueError as exc:
            msg = f"material at {directory} is damaged or incomplete: {exc}"
            raise ValueError(msg) from exc
