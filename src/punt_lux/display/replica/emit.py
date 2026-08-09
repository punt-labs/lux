"""The Display's emit channel default."""

from __future__ import annotations

from typing import Self

__all__ = ["NoOpEmit"]


class NoOpEmit:
    """Null Object emit channel for the Display's own wire decode.

    A decoded replica has no channel to emit on: the Display forwards
    interactions to the Hub over its socket, never through an element's emit.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, _msg: object) -> None:
        """Drop the message — the Display has no emit channel."""
