"""Scenario — declarative description of one business-event-loop case.

A scenario is data, not a bespoke test function. It names the element
tree to show, the interactive element to inject, what that interaction
must look like at the boundary (``InteractionExpectation``), how the
target announces its business event (``PublishSource``), what the
handler-driven dispatch re-push must reflect (``RepushEffect``), the
agent's multi-patch return-path reaction, and the display-only leaf whose
re-pushed presence proves a mixed interactive/non-interactive composition
round-tripped.

The loop invariants (I1-I6) are expressed once in ``invariants.py`` and
run over every registered scenario, reading these fields — so adding a
migrated element is one more ``Scenario`` value, not new assertion code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from .publish_source import PayloadPublish, PublishSource, WirePublish
from .repush_effect import PropAfterDispatch, RemovedAfterDispatch, RepushEffect

__all__ = ["SCENARIOS", "InteractionExpectation", "ReactPatch", "Scenario"]


@dataclass(frozen=True, slots=True)
class InteractionExpectation:
    """The boundary shape one injected interaction must produce (I1).

    ``event_kind`` is the wire discriminator the Hub reads
    (``button_clicked`` / ``value_changed``); ``value`` is the wire
    payload the ``RemoteDispatchGroup`` stamps — ``True`` for a button, the
    new boolean for a checkbox toggle.
    """

    event_kind: str
    value: object


@dataclass(frozen=True, slots=True)
class ReactPatch:
    """One field the agent patches on the return path (I5).

    After the agent receives the published business event it reacts by
    setting ``field`` to ``value`` on ``element_id`` and re-pushing. A
    realistic reaction is several patches at once (advance a bar AND
    relabel it), so a scenario carries a tuple of these.
    """

    element_id: str
    field: str
    value: object


@dataclass(frozen=True, slots=True)
class Scenario:
    """One composed surface plus the full loop it must round-trip."""

    name: str
    scene_id: str
    elements: tuple[Mapping[str, object], ...]
    target_element_id: str
    interaction: InteractionExpectation
    publish: PublishSource
    react: tuple[ReactPatch, ...]
    display_only_id: str
    repush: RepushEffect

    @property
    def topic(self) -> str:
        """Return the business topic the agent subscribes and I3 asserts."""
        return self.publish.topic

    @classmethod
    def group_button_progress(cls) -> Self:
        """A group holding a publishing button and a display-only progress.

        The button publishes ``ticket_opened`` (wire sugar, empty payload)
        on click; its noop+publish handler does not touch scene state, so
        the dispatch re-push carries the button unchanged. The agent reacts
        by advancing and relabelling the progress bar.
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
            interaction=InteractionExpectation(event_kind="button_clicked", value=True),
            publish=WirePublish("ticket_opened"),
            react=(
                ReactPatch(element_id="ticket-progress", field="fraction", value=1.0),
                ReactPatch(element_id="ticket-progress", field="label", value="done"),
            ),
            display_only_id="ticket-progress",
            repush=PropAfterDispatch(
                element_id="open-ticket", field="label", value="Open ticket"
            ),
        )

    @classmethod
    def group_checkbox_progress(cls) -> Self:
        """A group holding a publishing checkbox and a display-only progress.

        Toggling the checkbox crosses as ``value_changed`` (value ``True``);
        the built-in state-sync handler flips the Hub value ``False``→``True``,
        so the dispatch re-push carries the mutated value. A wire ``handlers``
        entry publishes ``box_toggled``.
        """
        return cls(
            name="group-checkbox-progress",
            scene_id="e2e-checkbox-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "chk-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "checkbox",
                            "id": "toggle-box",
                            "label": "Toggle",
                            "value": False,
                            "handlers": [
                                {
                                    "event": "changed",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["box_toggled"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "chk-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="toggle-box",
            interaction=InteractionExpectation(event_kind="value_changed", value=True),
            publish=WirePublish("box_toggled"),
            react=(
                ReactPatch(element_id="chk-progress", field="fraction", value=1.0),
                ReactPatch(element_id="chk-progress", field="label", value="checked"),
            ),
            display_only_id="chk-progress",
            repush=PropAfterDispatch(
                element_id="toggle-box", field="value", value=True
            ),
        )

    @classmethod
    def collapsing_header_toggle_progress(cls) -> Self:
        """A collapsing_header beside a display-only progress (the interactive loop).

        The injected interaction is a ``header_toggled`` carrying ``True``; the
        built-in state-sync flips the Hub ``open`` ``False``→``True``, so the
        dispatch re-push carries the mutated ``open``. A wire ``handlers`` entry
        publishes ``header_expanded``; the agent reacts by advancing the bar.
        This proves the header toggle crosses the faithful boundary, the Hub
        updates the authoritative view-state once, and the re-push reflects it.
        """
        return cls(
            name="collapsing-header-toggle-progress",
            scene_id="e2e-header-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "hdr-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "collapsing_header",
                            "id": "disclosure",
                            "label": "Details",
                            "open": False,
                            "children": (
                                {"kind": "text", "id": "hdr-body", "content": "hidden"},
                            ),
                            "handlers": [
                                {
                                    "event": "header_toggled",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["header_expanded"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "hdr-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="disclosure",
            interaction=InteractionExpectation(event_kind="header_toggled", value=True),
            publish=WirePublish("header_expanded"),
            react=(
                ReactPatch(element_id="hdr-progress", field="fraction", value=1.0),
                ReactPatch(element_id="hdr-progress", field="label", value="expanded"),
            ),
            display_only_id="hdr-progress",
            repush=PropAfterDispatch(element_id="disclosure", field="open", value=True),
        )

    @classmethod
    def collapsing_header_button_progress(cls) -> Self:
        """A collapsing_header whose child publishes (the child-forwarding loop).

        The header holds a publishing ``button`` and a display-only ``progress``.
        The button — not the header — is the injected target; it publishes
        ``ticket_opened``. This proves the container forwards its child's D21
        wrap through the flattened children, complementing the interactive
        Scenario's proof that the container wraps *itself*.
        """
        return cls(
            name="collapsing-header-button-progress",
            scene_id="e2e-header-child-scene",
            elements=(
                {
                    "kind": "collapsing_header",
                    "id": "section",
                    "label": "Actions",
                    "open": True,
                    "children": (
                        {
                            "kind": "button",
                            "id": "open-ticket",
                            "label": "Open ticket",
                            "publish": ["ticket_opened"],
                        },
                        {
                            "kind": "progress",
                            "id": "hdr-child-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="open-ticket",
            interaction=InteractionExpectation(event_kind="button_clicked", value=True),
            publish=WirePublish("ticket_opened"),
            react=(
                ReactPatch(
                    element_id="hdr-child-progress", field="fraction", value=1.0
                ),
                ReactPatch(
                    element_id="hdr-child-progress", field="label", value="done"
                ),
            ),
            display_only_id="hdr-child-progress",
            repush=PropAfterDispatch(
                element_id="open-ticket", field="label", value="Open ticket"
            ),
        )

    @classmethod
    def tab_bar_change_progress(cls) -> Self:
        """A tab bar beside a display-only progress (the interactive loop).

        The injected interaction is a ``tab_changed`` carrying the second tab's
        stable ``tab_id`` (never an index, DES-045); the built-in state-sync
        flips the Hub ``active_tab`` ``overview``→``details``, so the re-push
        carries the mutated selection. A wire ``handlers`` entry publishes
        ``tab_selected``; the agent reacts by advancing the bar.
        """
        return cls(
            name="tab-bar-change-progress",
            scene_id="e2e-tab-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "tab-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "tab_bar",
                            "id": "switcher",
                            "active_tab": "overview",
                            "tabs": (
                                {
                                    "id": "overview",
                                    "label": "Overview",
                                    "children": (
                                        {
                                            "kind": "text",
                                            "id": "ov-body",
                                            "content": "overview",
                                        },
                                    ),
                                },
                                {
                                    "id": "details",
                                    "label": "Details",
                                    "children": (
                                        {
                                            "kind": "text",
                                            "id": "dt-body",
                                            "content": "details",
                                        },
                                    ),
                                },
                            ),
                            "handlers": [
                                {
                                    "event": "tab_changed",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["tab_selected"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "tab-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="switcher",
            interaction=InteractionExpectation(
                event_kind="tab_changed", value="details"
            ),
            publish=WirePublish("tab_selected"),
            react=(
                ReactPatch(element_id="tab-progress", field="fraction", value=1.0),
                ReactPatch(element_id="tab-progress", field="label", value="switched"),
            ),
            display_only_id="tab-progress",
            repush=PropAfterDispatch(
                element_id="switcher", field="active_tab", value="details"
            ),
        )

    @classmethod
    def tab_bar_button_progress(cls) -> Self:
        """A tab bar whose active tab's child publishes (the child-forwarding loop).

        The active tab holds a publishing ``button`` and a display-only
        ``progress``. The button — not the tab bar — is the injected target; it
        publishes ``ticket_opened``. This proves the tab bar forwards its child's
        D21 wrap through the flattened tab children.
        """
        return cls(
            name="tab-bar-button-progress",
            scene_id="e2e-tab-child-scene",
            elements=(
                {
                    "kind": "tab_bar",
                    "id": "surface-tabs",
                    "active_tab": "main",
                    "tabs": (
                        {
                            "id": "main",
                            "label": "Main",
                            "children": (
                                {
                                    "kind": "button",
                                    "id": "open-ticket",
                                    "label": "Open ticket",
                                    "publish": ["ticket_opened"],
                                },
                                {
                                    "kind": "progress",
                                    "id": "tab-child-progress",
                                    "fraction": 0.0,
                                    "label": "idle",
                                },
                            ),
                        },
                    ),
                },
            ),
            target_element_id="open-ticket",
            interaction=InteractionExpectation(event_kind="button_clicked", value=True),
            publish=WirePublish("ticket_opened"),
            react=(
                ReactPatch(
                    element_id="tab-child-progress", field="fraction", value=1.0
                ),
                ReactPatch(
                    element_id="tab-child-progress", field="label", value="done"
                ),
            ),
            display_only_id="tab-child-progress",
            repush=PropAfterDispatch(
                element_id="open-ticket", field="label", value="Open ticket"
            ),
        )

    @classmethod
    def dialog_confirm_progress(cls) -> Self:
        """A dialog whose confirm mutates Hub state, beside a display-only leaf.

        Clicking the dialog's confirm button runs ``DialogModel.confirm`` on
        the Hub copy — recording confirmation and ``mark_removed`` — so the
        root-observer cascade drops the dialog from ``HubDisplay`` and the
        dispatch re-push carries the shrunken tree (the dialog is gone from
        the replica *before* the agent reacts). The confirm button also
        publishes ``ticket_confirmed``. The sibling progress survives the
        removal and carries the agent's reaction.
        """
        return cls(
            name="dialog-confirm-progress",
            scene_id="e2e-dialog-scene",
            elements=(
                {
                    "kind": "dialog",
                    "id": "confirm-dialog",
                    "title": "Confirm ticket",
                    "children": [
                        {
                            "kind": "button",
                            "id": "confirm-btn",
                            "label": "Confirm",
                            "click": "confirm",
                            "publish": ["ticket_confirmed"],
                        }
                    ],
                },
                {
                    "kind": "progress",
                    "id": "dlg-progress",
                    "fraction": 0.0,
                    "label": "idle",
                },
            ),
            target_element_id="confirm-btn",
            interaction=InteractionExpectation(event_kind="button_clicked", value=True),
            publish=WirePublish("ticket_confirmed"),
            react=(
                ReactPatch(element_id="dlg-progress", field="fraction", value=1.0),
                ReactPatch(element_id="dlg-progress", field="label", value="confirmed"),
            ),
            display_only_id="dlg-progress",
            repush=RemovedAfterDispatch("confirm-dialog"),
        )

    @classmethod
    def payload_button_progress(cls) -> Self:
        """A button whose Hub handler publishes a non-empty payload.

        The button carries no ``publish`` sugar; instead the agent wires a
        ``PublishingHandler`` that announces ``ticket_created`` with a
        non-empty payload through the real ``HubPublishSink`` — giving I3's
        payload assertion teeth. Scene state is untouched, so the dispatch
        re-push carries the button unchanged.
        """
        return cls(
            name="payload-button-progress",
            scene_id="e2e-payload-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "pay-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "button",
                            "id": "submit-btn",
                            "label": "Submit",
                        },
                        {
                            "kind": "progress",
                            "id": "pay-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="submit-btn",
            interaction=InteractionExpectation(event_kind="button_clicked", value=True),
            publish=PayloadPublish(
                topic="ticket_created", payload={"ticket_id": "T-42"}
            ),
            react=(
                ReactPatch(element_id="pay-progress", field="fraction", value=1.0),
                ReactPatch(element_id="pay-progress", field="label", value="created"),
            ),
            display_only_id="pay-progress",
            repush=PropAfterDispatch(
                element_id="submit-btn", field="label", value="Submit"
            ),
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
        return {key: self._copy_value(value) for key, value in elem.items()}

    def _copy_value(self, value: object) -> object:
        """Copy a wire value, recursing into child mappings and sequences."""
        if isinstance(value, Mapping):
            return self._deep_copy(value)
        if isinstance(value, (list, tuple)):
            return [self._copy_value(item) for item in value]
        return value


SCENARIOS: tuple[Scenario, ...] = (
    Scenario.group_button_progress(),
    Scenario.group_checkbox_progress(),
    Scenario.collapsing_header_toggle_progress(),
    Scenario.collapsing_header_button_progress(),
    Scenario.tab_bar_change_progress(),
    Scenario.tab_bar_button_progress(),
    Scenario.dialog_confirm_progress(),
    Scenario.payload_button_progress(),
)
