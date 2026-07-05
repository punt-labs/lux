"""Scenario — declarative description of one business-event-loop case.

A scenario is data, not a bespoke test function: it names the element
tree to show, the interactive element to inject, the business topic the
agent subscribes and expects, the agent's return-path reaction, and the
display-only leaf whose re-pushed presence proves the container
round-tripped a mixed interactive/non-interactive composition. The loop
invariants (I1-I6) are expressed once in ``invariants.py`` and run over
every registered scenario, so adding a migrated element is one more
``Scenario`` value, not new assertion code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class ReactStep:
    """The agent's return-path reaction: one field patch pushed back.

    After the agent receives the published business event, it reacts by
    setting ``field`` to ``value`` on the element named ``element_id`` and
    re-pushing the scene. The Display replica must then reflect the change
    (loop invariant I5).
    """

    element_id: str
    field: str
    value: object


@dataclass(frozen=True, slots=True)
class Scenario:
    """One composed surface plus the full loop it must round-trip.

    ``elements`` is the wire tree the agent ``show``s; the interactive
    target carries its business ``publish`` sugar inline so the real wire
    decoder wires the publish decorator. ``display_only_id`` names the
    non-interactive leaf whose presence in the re-pushed replica proves
    the container carried a mixed composition end to end.
    """

    name: str
    scene_id: str
    elements: tuple[Mapping[str, object], ...]
    target_element_id: str
    topic: str
    react: ReactStep
    display_only_id: str

    @classmethod
    def group_button_progress(cls) -> Self:
        """Return the first scenario: a group holding a button + a progress.

        The button publishes ``ticket_opened`` on click; the agent reacts
        by advancing the progress bar to full. The group is the composed
        migrated container; the progress is the display-only leaf that
        must survive the round trip.
        """
        return cls(
            name="group-button-progress",
            scene_id="e2e-loop-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "button",
                            "id": "open-ticket",
                            "label": "Open ticket",
                            "publish": ["ticket_opened"],
                        },
                        {
                            "kind": "progress",
                            "id": "ticket-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="open-ticket",
            topic="ticket_opened",
            react=ReactStep(element_id="ticket-progress", field="fraction", value=1.0),
            display_only_id="ticket-progress",
        )

    def wire_elements(self) -> list[dict[str, object]]:
        """Return a fresh mutable copy of the wire tree for ``show``.

        Deep-copies each mapping (and its nested ``children``) so a run
        never mutates the shared scenario literal — the wire decoder and
        the sugar canonicalizer both rewrite the dict they are handed.
        """
        return [self._deep_copy(elem) for elem in self.elements]

    def _deep_copy(self, elem: Mapping[str, object]) -> dict[str, object]:
        """Return a recursive plain-dict copy of one wire element."""
        out: dict[str, object] = {}
        for key, value in elem.items():
            out[key] = self._copy_value(value)
        return out

    def _copy_value(self, value: object) -> object:
        """Copy a wire value, recursing into child mappings and sequences."""
        if isinstance(value, Mapping):
            return self._deep_copy(value)
        if isinstance(value, (list, tuple)):
            return [self._copy_value(item) for item in value]
        return value


SCENARIOS: tuple[Scenario, ...] = (Scenario.group_button_progress(),)

__all__ = ["SCENARIOS", "ReactStep", "Scenario"]
