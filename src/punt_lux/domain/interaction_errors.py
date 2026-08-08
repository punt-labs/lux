"""Typed exceptions the Hub interaction dispatch raises on domain-validation
failure.

``HubInteractionDispatch`` drops and logs most invalid interactions rather
than raising (the Display is a replica; there is nobody local to hand an
exception to). ``WrongKindError`` is the one domain-validation failure that
still raises, at the element-mutation call site (``wire_value.py``,
``event_handler_host.py``) rather than the dispatch itself.

Distinct from ``domain.error`` and ``domain.ownership``, which house
lookup/validation failures modeled as data (per PY-EH-8) rather than as
exceptions -- ``HubDisplay.apply`` itself enforces those same failures
by raising today, so the two families no longer split cleanly along
"apply returns this / interact raises that"; they remain separate
modules because they model the failure differently (value vs.
exception), not because of which call site produces each.
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
