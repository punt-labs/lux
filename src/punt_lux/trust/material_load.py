"""MaterialLoad — wrap a load failure with directory context.

A save interrupted mid-write leaves a damaged, partial, or missing file
whose bare ``ValueError``/``OSError`` names no directory. This re-wraps
either into a message naming the directory — a clear error, not a
silent break.
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
        """Load trust material and report damaged or missing data with its directory."""
        try:
            return load()
        except (ValueError, OSError) as exc:
            msg = f"material at {directory} is damaged or incomplete: {exc}"
            raise ValueError(msg) from exc
