"""Typed exceptions the Hub interaction dispatch raises on domain-validation
failure.

``HubInteractionDispatch`` drops and logs most invalid interactions rather
than raising (the Display is a replica; there is nobody local to hand an
exception to). ``WrongKindError`` is the one domain-validation failure that
still raises, at the element-mutation call site (``wire_value.py``,
``event_handler_host.py``) rather than the dispatch itself.

Distinct from ``domain.error`` and ``domain.ownership``, which house the
dataclass response types ``HubDisplay.apply`` *returns* (the success-or-error
union). The two error families are deliberately separate: ``apply`` returns
errors as values because every Update's outcome is one of a discriminated
union; a wire-kind mismatch raises because it signals a caller sending a
value shape its own declared kind cannot accept.
"""

from __future__ import annotations

from dataclasses import dataclass

from punt_lux.domain.ids import ElementId, SceneId

__all__ = [
    "InteractionError",
    "WrongKindError",
]


@dataclass(frozen=True, slots=True)
class InteractionError(Exception):
    """Base class for every interaction domain failure."""

    def __str__(self) -> str:
        return self.__class__.__name__


@dataclass(frozen=True, slots=True)
class WrongKindError(InteractionError):
    """Element's wire kind does not match the interaction value shape."""

    scene_id: SceneId
    element_id: ElementId
    expected: str
    got: str

    def __str__(self) -> str:
        return (
            f"element {self.element_id!r} in scene {self.scene_id!r}: "
            f"expected {self.expected}, got {self.got}"
        )
