"""Hierarchy-walking validation collector.

The walk is the aggregating half of the self-validating-element model.
Each element decides what "valid" means for *itself* by implementing
:class:`SelfValidating`; the walk visits every element in a tree, calls
that per-element ``validate()``, and accumulates all errors — it never
fails fast. A composite exposes its children through
:class:`HasChildElements` so its subtree is covered by the same walk.

Both protocols are ``runtime_checkable`` so the walk works uniformly
over two element models: the frozen wire dataclasses (which opt in by
defining the methods) and the behavioral :class:`~punt_lux.domain.element_abc.Element`
ABC (which supplies both as defaults). An element that implements neither
contributes no errors and no children — the sensible leaf default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.domain.validation import ValidationReport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.validation import ValidationError

__all__ = ["ElementTreeValidator", "HasChildElements", "SelfValidating"]


@runtime_checkable
class SelfValidating(Protocol):
    """An element that checks its own inputs against its widget contract."""

    def validate(self) -> tuple[ValidationError, ...]:
        """Return this element's own validation errors (empty if valid)."""
        ...


@runtime_checkable
class HasChildElements(Protocol):
    """A composite that can enumerate its direct children for the walk."""

    def child_elements(self) -> tuple[object, ...]:
        """Return the direct child elements to recurse into."""
        ...


@final
class ElementTreeValidator:
    """Walks an element tree and collects every element's self-validation.

    Stateless. The walk is a Visitor over the heterogeneous element tree — it
    asks each element whether it self-validates and whether it has children, and
    accumulates errors across the hierarchy into one :class:`ValidationReport`.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def validate_tree(self, elements: Sequence[object]) -> ValidationReport:
        """Collect validation errors across ``elements`` and their subtrees."""
        sink: list[ValidationError] = []
        for element in elements:
            self._visit(element, sink)
        return ValidationReport(tuple(sink))

    def _visit(self, element: object, sink: list[ValidationError]) -> None:
        """Accumulate ``element``'s own errors, then recurse into children."""
        if isinstance(element, SelfValidating):
            sink.extend(element.validate())
        if isinstance(element, HasChildElements):
            for child in element.child_elements():
                self._visit(child, sink)
