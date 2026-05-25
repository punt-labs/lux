"""Typed exceptions ``Display.interact`` raises on domain-validation failure.

These exceptions are the *output* of the domain validation site for a wire
``InteractionMessage``. ``Display.interact`` catches none of them; the
caller is responsible for translating them to whatever log / wire payload
shape the boundary needs.

Distinct from ``domain.error`` and ``domain.ownership``, which house the
dataclass response types ``Display.apply`` *returns* (the success-or-error
union). The two error families are deliberately separate: ``apply``
returns errors as values because every Update's outcome is one of a
discriminated union; ``interact`` raises because every wire-shape-valid
``InteractionMessage`` is meant to land on a real Element, and a domain
mismatch is an exceptional condition, not a normal value.
"""

from __future__ import annotations

from dataclasses import dataclass

from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = [
    "InteractionError",
    "UnauthorizedInteractionError",
    "UnknownClientError",
    "UnknownInteractionElementError",
    "UnknownInteractionSceneError",
    "WrongKindError",
]


@dataclass(frozen=True, slots=True)
class InteractionError(Exception):
    """Base class for every ``Display.interact`` domain failure.

    Subclasses carry the structured context the caller needs to log or
    re-raise; this base lets handlers ``except InteractionError`` to drop
    every validation failure at the boundary with one handler.
    """

    def __str__(self) -> str:
        return self.__class__.__name__


@dataclass(frozen=True, slots=True)
class UnknownClientError(InteractionError):
    """Caller's ``client_id`` is not registered with the Display."""

    client_id: ClientId

    def __str__(self) -> str:
        return f"unknown client: {self.client_id!r}"


@dataclass(frozen=True, slots=True)
class UnknownInteractionSceneError(InteractionError):
    """Interaction targeted a scene the Display does not know."""

    scene_id: SceneId

    def __str__(self) -> str:
        return f"unknown scene: {self.scene_id!r}"


@dataclass(frozen=True, slots=True)
class UnknownInteractionElementError(InteractionError):
    """Interaction targeted an element id absent from the named scene."""

    scene_id: SceneId
    element_id: ElementId

    def __str__(self) -> str:
        return f"unknown element {self.element_id!r} in scene {self.scene_id!r}"


@dataclass(frozen=True, slots=True)
class UnauthorizedInteractionError(InteractionError):
    """Caller did not own the element they tried to interact with."""

    scene_id: SceneId
    element_id: ElementId
    caller: ClientId

    def __str__(self) -> str:
        return (
            f"client {self.caller!r} cannot interact with element "
            f"{self.element_id!r} in scene {self.scene_id!r}"
        )


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
