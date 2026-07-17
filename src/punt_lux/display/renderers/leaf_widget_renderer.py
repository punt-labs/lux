"""Structural contract for a renderer that paints one element kind."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.protocol import Element

__all__ = ["LeafWidgetRenderer"]


@runtime_checkable
class LeafWidgetRenderer(Protocol):
    """Paint one element kind through a single ``render`` call.

    The single-method family contract every per-kind renderer satisfies
    structurally — no base class. Implementations may be stateless (a
    self-contained widget) or compose injected collaborators (an
    ``emit_event`` callback, or widget state plus a recursive child render).
    """

    def render(self, elem: Element) -> None:
        """Paint ``elem`` as an ImGui widget."""
        ...
