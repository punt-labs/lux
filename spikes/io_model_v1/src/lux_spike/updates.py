"""Update sum + Event sum + InteractionMessage.

Per io-model.md §"Where rendering happens": IPC carries Updates and Events.
NOT render calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lux_spike.element import Element


@dataclass(frozen=True, slots=True)
class AddElement:
    """Hub → Display: add a new Element under the named parent (or as
    scene root if parent is None)."""

    scene_id: str
    parent_id: str | None
    elem: Element


@dataclass(frozen=True, slots=True)
class SetProperty:
    """Hub → Display: mutate one field on one Element."""

    elem_id: str
    field: str
    value: object


# Update sum
type Update = AddElement | SetProperty


@dataclass(frozen=True, slots=True)
class ButtonClicked:
    """Event: emitted by ButtonElement.on_click(); the Hub publishes it
    to the interaction.<elem_id> topic for subscribed agents."""

    elem_id: str


@dataclass(frozen=True, slots=True)
class PropertyChanged:
    """Event: emitted when SetProperty applies. Forward-looking; not
    used by the spike's three roundtrips but defined for completeness."""

    elem_id: str
    field: str


# Event sum
type Event = ButtonClicked | PropertyChanged


@dataclass(frozen=True, slots=True)
class InteractionMessage:
    """Display → Hub: user input detected on the Display tier. The Hub
    looks up the Element on its own tier and invokes the behavior method."""

    elem_id: str
    action: str  # "click" for PR-3 spike scope
