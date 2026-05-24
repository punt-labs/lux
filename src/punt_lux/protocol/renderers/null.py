"""NullRenderer + NullRendererFactory — for tiers that never paint.

Per docs/oo-refactor/pr3-v2.1-design.md §1 row 6 and io-model.md
§"NullRendererFactory": the Hub injects this factory into its decoded
Elements so the constructor signature stays uniform across tiers; the
Hub never iterates its scene for drawing, so the factory's renderers
are dead weight kept for shape.
"""

from __future__ import annotations

from typing import Self

__all__ = ["NullRenderer", "NullRendererFactory"]


class NullRenderer:
    """Renderer that does nothing for any of the three Protocol calls.

    Null Object (PY-DP-9): every method satisfies the Renderer Protocol
    by returning ``None``; none access ``self``.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self) -> None:
        """No-op leaf render."""

    def begin(self) -> None:
        """No-op composite begin."""

    def end(self) -> None:
        """No-op composite end."""


_NULL = NullRenderer()


class NullRendererFactory:
    """Factory that returns the shared NullRenderer for every element."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, elem: object) -> NullRenderer:
        """Return the shared NullRenderer regardless of element."""
        del elem
        return _NULL
