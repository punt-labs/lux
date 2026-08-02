"""``EventPayload`` — the mapping a published interaction event carries.

Every event a ``publish``-decorated handler announces says the same three
things first: *what* happened (the event's wire ``kind``), and *where* — the
scene and the element the user touched. Those three keys are the contract a
subscriber reads before it looks at anything else, so they live here once
rather than being spelled out in each event's ``to_payload``.

The owner is deliberately absent. Publish fan-out is scoped to the publishing
connection (``Hub.publish`` snapshots subscribers under one ``ConnectionId``),
so a subscriber only ever receives events from its own scope and the owning
client's id answers no question it can ask.

An event composes this and adds its own fields — a row selection adds its
``row_ids`` and ``anchor``, a value input adds its ``value``. Values must be
JSON types: the payload crosses to the agent over the observer wire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["EventPayload", "LocatedEvent"]


@runtime_checkable
class LocatedEvent(Protocol):
    """An event that knows where it happened."""

    @property
    def scene_id(self) -> SceneId:
        """Return the scene the interaction targeted."""
        ...

    @property
    def element_id(self) -> ElementId:
        """Return the element the interaction targeted."""
        ...


@final
class EventPayload:
    """The identity keys every published event payload opens with."""

    _kind: str
    _scene_id: SceneId
    _element_id: ElementId
    __slots__ = ("_element_id", "_kind", "_scene_id")

    def __new__(
        cls,
        *,
        kind: str,
        scene_id: SceneId,
        element_id: ElementId,
    ) -> Self:
        self = super().__new__(cls)
        self._kind = kind
        self._scene_id = scene_id
        self._element_id = element_id
        return self

    @classmethod
    def of(cls, event: LocatedEvent, kind: str) -> Self:
        """Return the identity ``event`` publishes under.

        The scene and element are read off the event rather than copied out by
        each ``to_payload``, so what "identity" means is stated once. ``kind``
        is passed instead: a concrete event spells it ``ClassVar[Literal[...]]``,
        which no protocol member satisfies under both type checkers (the reason
        ``WireEvent`` leaves it off as well).
        """
        return cls(kind=kind, scene_id=event.scene_id, element_id=event.element_id)

    def to_mapping(self, **fields: object) -> dict[str, object]:
        """Return the payload: the identity keys, then the event's own ``fields``.

        The three identity names belong to this class, so an event names its own
        fields something else; ``test_event_payload`` holds every event to that.
        """
        return {
            "kind": self._kind,
            "scene_id": self._scene_id,
            "element_id": self._element_id,
            **fields,
        }
