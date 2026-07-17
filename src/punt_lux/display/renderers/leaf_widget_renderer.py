"""Structural contract for a stateless leaf-widget painter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.protocol import Element

__all__ = ["LeafWidgetRenderer"]


@runtime_checkable
class LeafWidgetRenderer(Protocol):
    """Paint one element as an ImGui widget.

    The single-method family contract every per-kind renderer satisfies
    structurally — no base class. ``isinstance(x, LeafWidgetRenderer)``
    asserts membership at runtime; the concrete renderers narrow ``elem``
    to their own element type.
    """

    def render(self, elem: Element) -> None:
        """Paint ``elem`` as an ImGui widget."""
        ...
