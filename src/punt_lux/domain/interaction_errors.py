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

from typing import Self

from punt_lux.domain.ids import ElementId, SceneId

__all__ = [
    "InteractionError",
    "WrongKindError",
]


class InteractionError(Exception):
    """Base class for every interaction domain failure."""

    def __str__(self) -> str:
        return self.__class__.__name__


class WrongKindError(InteractionError):
    """Element's wire kind does not match the interaction value shape."""

    _scene_id: SceneId
    _element_id: ElementId
    _expected: str
    _got: str

    def __new__(
        cls, scene_id: SceneId, element_id: ElementId, expected: str, got: str
    ) -> Self:
        self = super().__new__(cls, scene_id, element_id, expected, got)
        self._scene_id = scene_id
        self._element_id = element_id
        self._expected = expected
        self._got = got
        return self

    @property
    def scene_id(self) -> SceneId:
        """The scene of the element."""
        return self._scene_id

    @property
    def element_id(self) -> ElementId:
        """The element that was fired at."""
        return self._element_id

    @property
    def expected(self) -> str:
        """The wire kinds the element answers to."""
        return self._expected

    @property
    def got(self) -> str:
        """What the invocation carried."""
        return self._got

    def __str__(self) -> str:
        return (
            f"element {self._element_id!r} in scene {self._scene_id!r}: "
            f"expected {self._expected}, got {self._got}"
        )
