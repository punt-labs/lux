"""Typed interaction events for the Hub-authoritative container interactions.

Each interactive container routes one gesture down the same remote-dispatch path
as ``ButtonClicked``: a ``collapsing_header``'s open state (``HeaderToggled``), a
``tab_bar``'s active tab (``TabChanged``), or a ``modal``'s user dismissal
(``ModalClosed``). The Hub runs the container's authoritative reaction — mirror
the selection, or dismiss the modal — and re-pushes. Kept apart from the
``interaction`` leaf events so no module holds more than three classes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.domain.event_payload import EventPayload
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.wire_value import WireValue

__all__ = ["HeaderToggled", "ModalClosed", "TabChanged"]


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

    @classmethod
    def from_wire(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> Self:
        """Build the tab-change event; the payload must be the new tab's id."""
        return cls(
            scene_id=scene_id,
            element_id=element_id,
            owner_id=owner_id,
            tab_id=WireValue(value, scene_id=scene_id, element_id=element_id).as_str(
                "a tab_changed payload (str tab_id)"
            ),
        )

    def to_payload(self) -> Mapping[str, object]:
        """Return the published payload: identity plus the newly-active ``tab_id``."""
        return EventPayload.of(self, self.kind).to_mapping(tab_id=self.tab_id)


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

    @classmethod
    def from_wire(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> Self:
        """Build the header-toggle event; the payload must be the new open state."""
        return cls(
            scene_id=scene_id,
            element_id=element_id,
            owner_id=owner_id,
            open_=WireValue(value, scene_id=scene_id, element_id=element_id).as_bool(
                "a header_toggled payload (bool open state)"
            ),
        )

    def to_payload(self) -> Mapping[str, object]:
        """Return the published payload: identity plus the new ``open`` state."""
        return EventPayload.of(self, self.kind).to_mapping(open=self.open)


@dataclass(frozen=True, slots=True, init=False)
class ModalClosed:
    """A typed dismissal event for a ``modal`` — the user closed it.

    Unlike the other container events it carries no selection payload: a close
    has no value beyond "it happened". The Hub fires the modal's built-in dismiss
    handler (``model.close`` -> ``mark_removed``) so the removal cascade drops the
    modal from both tiers. Same ``init=False`` + ``__new__`` construction as the
    leaf events.
    """

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    kind: ClassVar[Literal["modal_closed"]] = "modal_closed"

    def __new__(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
    ) -> Self:
        self = object.__new__(cls)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "element_id", element_id)
        object.__setattr__(self, "owner_id", owner_id)
        return self

    @classmethod
    def from_wire(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> Self:
        """Build the dismissal event; a close carries no payload, so ignore value."""
        _ = value  # payload-less event; the shared WireEvent signature carries it
        return cls(scene_id=scene_id, element_id=element_id, owner_id=owner_id)

    def to_payload(self) -> Mapping[str, object]:
        """Return the published payload: identity alone — a close carries no data."""
        return EventPayload.of(self, self.kind).to_mapping()
