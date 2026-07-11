"""Typed interaction events for the Hub-authoritative container view-selections.

An interactive container carries one discrete, agent-drivable view-selection:
a ``collapsing_header`` owns whether the section is open. The event a user
gesture fires travels the same D21 path as ``ButtonClicked`` / ``ValueChanged``
— it routes to the Hub, the Hub updates the authoritative selection, and the
whole scene is re-pushed. These events live apart from the leaf events in
``interaction`` so each module keeps at most three classes (PY-OO-2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["HeaderToggled"]


@dataclass(frozen=True, slots=True, init=False)
class HeaderToggled:
    """A typed open/collapse event for a ``collapsing_header``.

    Same construction pattern as ``ValueChanged`` — ``init=False`` with
    ``__new__`` the sole construction path. Carries the new ``open`` state
    the user's toggle produced; the Hub mirrors it onto the authoritative
    element and re-pushes.
    """

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    open: bool
    kind: ClassVar[Literal["header_toggled"]] = "header_toggled"

    def __new__(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        open_: bool,
    ) -> Self:
        # ``open_`` avoids shadowing the ``open`` builtin at the parameter
        # (PEP 8 trailing-underscore); the payload attribute stays ``open`` to
        # match the wire key and the element field.
        self = object.__new__(cls)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "element_id", element_id)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "open", open_)
        return self
