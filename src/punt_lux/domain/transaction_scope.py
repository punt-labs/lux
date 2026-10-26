"""TransactionScope -- what a transaction in force answers to.

Three messages for three meanings, so no one reads a meaning out of an empty patch: an
element is *written* (judge it, record it), an element is *about to derive* state no
patch names (checkpoint it, do not count it as written), and an element is *removed*
(take custody; carry the removal out once the transaction stood).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element

__all__ = ["TransactionScope"]


class TransactionScope(Protocol):
    """The transaction a handler's writes are made in."""

    def admit(self, element: Element, patch: Mapping[str, object]) -> None:
        """Judge a write to ``element`` before it is made; raise to refuse it."""
        ...

    def note_derivation(self, element: Element) -> None:
        """Checkpoint ``element``: it is about to change state no patch names."""
        ...

    def defer_removal(self, element: Element) -> None:
        """Take custody of ``element``'s removal, to carry out once everything stood."""
        ...
