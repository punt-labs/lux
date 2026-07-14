"""Typed interaction events for the Hub-authoritative container view-selections.

Each interactive container owns one agent-drivable selection: a
``collapsing_header``'s open state (``HeaderToggled``) or a ``tab_bar``'s active
tab (``TabChanged``). A gesture routes it down the same remote-dispatch path as
``ButtonClicked`` — the Hub updates the authoritative selection and re-pushes.
Kept apart from the ``interaction`` leaf events so no module exceeds three classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["HeaderToggled", "TabChanged"]


@dataclass(frozen=True, slots=True, init=False)
class TabChanged:
    """A typed active-tab-change event for a ``tab_bar``.

    Carries the newly-selected tab's stable ``tab_id`` (never a positional
    index). The Hub mirrors it onto the authoritative element and
    re-pushes. Same ``init=False`` + ``__new__`` construction pattern as the
    leaf events.
    """

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    tab_id: str
    kind: ClassVar[Literal["tab_changed"]] = "tab_changed"

    def __new__(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        tab_id: str,
    ) -> Self:
        self = object.__new__(cls)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "element_id", element_id)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "tab_id", tab_id)
        return self


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
