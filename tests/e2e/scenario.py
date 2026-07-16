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

__all__ = [
    "COLOR_COMMIT_VALUE",
    "COMBO_COMMIT_INDEX",
    "INPUT_COMMIT_TEXT",
    "NUMBER_COMMIT_VALUE",
    "RADIO_COMMIT_INDEX",
    "SCENARIOS",
    "SLIDER_COMMIT_VALUE",
    "InteractionExpectation",
    "ReactPatch",
    "Scenario",
]

# The text an input_text edit commits in the loop. Shared with the agent's
# synthetic-event builder so the injected interaction and the re-push assertion
# agree (an edit has no structural source for its text, unlike a tab switch).
INPUT_COMMIT_TEXT = "Ada Lovelace"

# The float a slider drag commits in the loop — in range for the scenario's
# [0, 100] slider. Shared with the agent's synthetic-event builder for the same
# reason: a drag has no structural source for its value.
SLIDER_COMMIT_VALUE = 42.5

# The hex color a color_picker drag commits in the loop. Shared with the agent's
# synthetic-event builder for the same reason: a color drag has no structural
# source for its value.
COLOR_COMMIT_VALUE = "#3366CC"

# The number an input_number edit commits in the loop — in range for the
# scenario's [0, 100] input. Shared with the agent's synthetic-event builder for
# the same reason: a typed number has no structural source for its value.
NUMBER_COMMIT_VALUE = 33.0

# The index a combo pick commits in the loop — the second item of the scenario's
# three-item combo. Shared with the agent's synthetic-event builder: a pick's
# structural source is the chosen index, but the agent injects a fixed target.
COMBO_COMMIT_INDEX = 1

# The index a radio pick commits in the loop — the second item of the scenario's
# three-item radio group. Shared with the agent's synthetic-event builder for the
# same reason as the combo: the agent injects a fixed target index.
RADIO_COMMIT_INDEX = 1


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
                element_id="toggle-box", field="value", value=True, flipped=True
            ),
        )

    @classmethod
    def group_input_text_progress(cls) -> Self:
        """A group holding a publishing input_text and a display-only progress.

        Committing an edit crosses as ``value_changed`` carrying the final text;
        the built-in state-sync handler writes the Hub ``value`` (``""`` -> the
        committed text), so the dispatch re-push carries the mutated text. A wire
        ``handlers`` entry publishes ``name_entered``; the agent reacts by
        advancing the bar.
        """
        return cls(
            name="group-input-text-progress",
            scene_id="e2e-input-text-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "it-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "input_text",
                            "id": "name-field",
                            "label": "Name",
                            "value": "",
                            "handlers": [
                                {
                                    "event": "changed",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["name_entered"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "it-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="name-field",
            interaction=InteractionExpectation(
                event_kind="value_changed", value=INPUT_COMMIT_TEXT
            ),
            publish=WirePublish("name_entered"),
            react=(
                ReactPatch(element_id="it-progress", field="fraction", value=1.0),
                ReactPatch(element_id="it-progress", field="label", value="entered"),
            ),
            display_only_id="it-progress",
            repush=PropAfterDispatch(
                element_id="name-field",
                field="value",
                value=INPUT_COMMIT_TEXT,
                flipped=True,
            ),
        )

    @classmethod
    def group_slider_progress(cls) -> Self:
        """A group holding a publishing slider and a display-only progress.

        Committing a drag crosses as ``value_changed`` carrying the final float;
        the built-in state-sync handler writes the Hub ``value`` (``0`` -> the
        committed float), so the dispatch re-push carries the mutated value. A
        wire ``handlers`` entry publishes ``level_changed``; the agent reacts by
        advancing the bar.
        """
        return cls(
            name="group-slider-progress",
            scene_id="e2e-slider-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "sl-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "slider",
                            "id": "level-field",
                            "label": "Level",
                            "value": 0.0,
                            "min": 0.0,
                            "max": 100.0,
                            "handlers": [
                                {
                                    "event": "changed",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["level_changed"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "sl-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="level-field",
            interaction=InteractionExpectation(
                event_kind="value_changed", value=SLIDER_COMMIT_VALUE
            ),
            publish=WirePublish("level_changed"),
            react=(
                ReactPatch(element_id="sl-progress", field="fraction", value=1.0),
                ReactPatch(element_id="sl-progress", field="label", value="set"),
            ),
            display_only_id="sl-progress",
            repush=PropAfterDispatch(
                element_id="level-field",
                field="value",
                value=SLIDER_COMMIT_VALUE,
                flipped=True,
            ),
        )

    @classmethod
    def group_input_number_progress(cls) -> Self:
        """A group holding a publishing input_number and a display-only progress.

        Committing an edit crosses as ``value_changed`` carrying the final number;
        the built-in state-sync handler writes the Hub ``value`` (``0`` -> the
        committed number), so the dispatch re-push carries the mutated value. A
        wire ``handlers`` entry publishes ``qty_changed``; the agent reacts by
        advancing the bar. Proves the fourth non-atomic mutable kind rides the
        faithful boundary as a plain number, exactly like the slider.
        """
        return cls(
            name="group-input-number-progress",
            scene_id="e2e-input-number-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "in-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "input_number",
                            "id": "qty-field",
                            "label": "Qty",
                            "value": 0.0,
                            "min": 0.0,
                            "max": 100.0,
                            "handlers": [
                                {
                                    "event": "changed",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["qty_changed"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "in-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="qty-field",
            interaction=InteractionExpectation(
                event_kind="value_changed", value=NUMBER_COMMIT_VALUE
            ),
            publish=WirePublish("qty_changed"),
            react=(
                ReactPatch(element_id="in-progress", field="fraction", value=1.0),
                ReactPatch(element_id="in-progress", field="label", value="entered"),
            ),
            display_only_id="in-progress",
            repush=PropAfterDispatch(
                element_id="qty-field",
                field="value",
                value=NUMBER_COMMIT_VALUE,
                flipped=True,
            ),
        )

    @classmethod
    def group_color_picker_progress(cls) -> Self:
        """A group holding a publishing color_picker and a display-only progress.

        Committing a drag crosses as ``value_changed`` carrying the final hex
        string; the built-in state-sync handler writes the Hub ``value``
        (``#FFFFFF`` -> the committed hex), so the dispatch re-push carries the
        mutated value. A wire ``handlers`` entry publishes ``color_changed``; the
        agent reacts by advancing the bar. Proves the migrated tuple-carrier
        picker rides the faithful boundary as a plain hex ``str``.
        """
        return cls(
            name="group-color-picker-progress",
            scene_id="e2e-color-picker-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "cp-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "color_picker",
                            "id": "fill-field",
                            "label": "Fill",
                            "value": "#FFFFFF",
                            "handlers": [
                                {
                                    "event": "changed",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["color_changed"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "cp-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="fill-field",
            interaction=InteractionExpectation(
                event_kind="value_changed", value=COLOR_COMMIT_VALUE
            ),
            publish=WirePublish("color_changed"),
            react=(
                ReactPatch(element_id="cp-progress", field="fraction", value=1.0),
                ReactPatch(element_id="cp-progress", field="label", value="picked"),
            ),
            display_only_id="cp-progress",
            repush=PropAfterDispatch(
                element_id="fill-field",
                field="value",
                value=COLOR_COMMIT_VALUE,
                flipped=True,
            ),
        )

    @classmethod
    def group_combo_progress(cls) -> Self:
        """A group holding a publishing combo and a display-only progress.

        Picking an item crosses as ``value_changed`` carrying the selected index
        (an ``int``); the built-in state-sync handler writes the Hub ``selected``
        (``0`` -> the picked index), so the dispatch re-push carries the mutated
        index. A wire ``handlers`` entry publishes ``option_selected``; the agent
        reacts by advancing the bar. Proves the atomic-selection combo rides the
        faithful boundary as a plain ``int`` index, like the checkbox's bool.
        """
        return cls(
            name="group-combo-progress",
            scene_id="e2e-combo-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "co-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "combo",
                            "id": "option-field",
                            "label": "Option",
                            "items": ("Alpha", "Beta", "Gamma"),
                            "selected": 0,
                            "handlers": [
                                {
                                    "event": "changed",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["option_selected"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "co-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="option-field",
            interaction=InteractionExpectation(
                event_kind="value_changed", value=COMBO_COMMIT_INDEX
            ),
            publish=WirePublish("option_selected"),
            react=(
                ReactPatch(element_id="co-progress", field="fraction", value=1.0),
                ReactPatch(element_id="co-progress", field="label", value="selected"),
            ),
            display_only_id="co-progress",
            repush=PropAfterDispatch(
                element_id="option-field",
                field="selected",
                value=COMBO_COMMIT_INDEX,
                flipped=True,
            ),
        )

    @classmethod
    def group_radio_progress(cls) -> Self:
        """A group holding a publishing radio and a display-only progress.

        Picking an item crosses as ``value_changed`` carrying the selected index
        (an ``int``); the built-in state-sync handler writes the Hub ``selected``
        (``0`` -> the picked index), so the dispatch re-push carries the mutated
        index. A wire ``handlers`` entry publishes ``choice_selected``; the agent
        reacts by advancing the bar. Proves the atomic-selection radio rides the
        faithful boundary as a plain ``int`` index, like the combo's.
        """
        return cls(
            name="group-radio-progress",
            scene_id="e2e-radio-scene",
            elements=(
                {
                    "kind": "group",
                    "id": "ra-surface",
                    "layout": "rows",
                    "children": (
                        {
                            "kind": "radio",
                            "id": "choice-field",
                            "label": "Choice",
                            "items": ("Alpha", "Beta", "Gamma"),
                            "selected": 0,
                            "handlers": [
                                {
                                    "event": "changed",
                                    "factory": "noop",
                                    "wrap": [
                                        {
                                            "decorator": "publish",
                                            "topics": ["choice_selected"],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "kind": "progress",
                            "id": "ra-progress",
                            "fraction": 0.0,
                            "label": "idle",
                        },
                    ),
                },
            ),
            target_element_id="choice-field",
            interaction=InteractionExpectation(
                event_kind="value_changed", value=RADIO_COMMIT_INDEX
            ),
            publish=WirePublish("choice_selected"),
            react=(
                ReactPatch(element_id="ra-progress", field="fraction", value=1.0),
                ReactPatch(element_id="ra-progress", field="label", value="selected"),
            ),
            display_only_id="ra-progress",
            repush=PropAfterDispatch(
                element_id="choice-field",
                field="selected",
                value=RADIO_COMMIT_INDEX,
                flipped=True,
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
            repush=PropAfterDispatch(
                element_id="disclosure", field="open", value=True, flipped=True
            ),
        )

    @classmethod
    def collapsing_header_button_progress(cls) -> Self:
        """A collapsing_header whose child publishes (the child-forwarding loop).

        The header holds a publishing ``button`` and a display-only ``progress``.
        The button — not the header — is the injected target; it publishes
        ``ticket_opened``. This proves the container forwards its child's remote
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
        stable ``tab_id`` (never an index); the built-in state-sync flips the
        Hub ``active_tab`` ``overview``→``details``, so the re-push
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
                element_id="switcher",
                field="active_tab",
                value="details",
                flipped=True,
            ),
        )

    @classmethod
    def tab_bar_button_progress(cls) -> Self:
        """A tab bar whose active tab's child publishes (the child-forwarding loop).

        The active tab holds a publishing ``button`` and a display-only
        ``progress``. The button — not the tab bar — is the injected target; it
        publishes ``ticket_opened``. This proves the tab bar forwards its child's
        remote wrap through the flattened tab children.
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
    Scenario.group_input_text_progress(),
    Scenario.group_slider_progress(),
    Scenario.group_input_number_progress(),
    Scenario.group_color_picker_progress(),
    Scenario.group_combo_progress(),
    Scenario.group_radio_progress(),
    Scenario.collapsing_header_toggle_progress(),
    Scenario.collapsing_header_button_progress(),
    Scenario.tab_bar_change_progress(),
    Scenario.tab_bar_button_progress(),
    Scenario.dialog_confirm_progress(),
    Scenario.payload_button_progress(),
)
