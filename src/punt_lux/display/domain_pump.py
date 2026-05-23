"""Dual-write pump: mirror native-kind SceneMessages into the domain Display."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, ClassVar, Self, cast

from punt_lux.domain.display import Display, Result
from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.event import (
    ButtonPressed,
    ElementAdded,
    ElementRemoved,
    ElementUpdated,
)
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.domain.update import AddElement, RemoveElement
from punt_lux.protocol import InteractionMessage, SceneMessage

__all__ = ["DomainPump"]

_log = logging.getLogger(__name__)


class DomainPump:
    """Mirror native-kind SceneMessages into a domain Display.

    "Native" = element kinds with their own per-class renderer in
    ``display.renderers``.  PR 1 shipped six (basics: Text, Image,
    Separator, Progress, Spinner, Markdown); PR 2 widens the set to
    fifteen by adding the nine inputs (Button, Slider, Checkbox, Combo,
    InputText, InputNumber, Radio, ColorPicker, Selectable).

    A scene containing only native kinds is routed through ``Display.apply``;
    a scene containing any non-native kind is skipped (mixed-scene rule —
    SceneManager owns those until subsequent PRs migrate the remaining
    families).
    """

    _display: Display
    _client_id: ClientId
    _native_kinds: tuple[type, ...]

    def __new__(
        cls,
        display: Display,
        client_id: ClientId,
        native_kinds: tuple[type, ...],
    ) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._client_id = client_id
        self._native_kinds = native_kinds
        return self

    def route(self, msg: SceneMessage) -> None:
        """Route a SceneMessage through the domain Display if it qualifies."""
        # Mixed-scene rule: any non-native element disqualifies the whole
        # scene from the new path.  An EMPTY element list must still clear
        # the scene — agents re-send empty scenes to clear the surface, and
        # skipping the clear lets the domain Display retain stale elements
        # while SceneManager drops them (Copilot CP-2).
        if any(not isinstance(elem, self._native_kinds) for elem in msg.elements):
            return
        scene_id = SceneId(msg.id)
        self._display.add_scene(scene_id)
        self._clear_scene(scene_id)
        for index, elem in enumerate(msg.elements):
            # cast: isinstance check above narrowed the element to a native
            # kind, every one of which satisfies the domain Element Protocol.
            domain_elem = self._with_unique_id(cast("DomainElement", elem), index=index)
            result = self._display.apply(
                self._client_id,
                AddElement(
                    scene_id=scene_id,
                    element=domain_elem,
                    parent_id=None,
                ),
            )
            _warn_on_error(
                result,
                scene_id=scene_id,
                element_id=ElementId(domain_elem.id),
                op="add",
            )

    @staticmethod
    def _with_unique_id(elem: DomainElement, *, index: int) -> DomainElement:
        """Return ``elem`` with ``<kind>:<index>`` id when its id is empty.

        Anonymous elements (``SeparatorElement``) collide in the
        Display's ``dict[ElementId, Element]`` when multiple appear in
        one scene; SceneManager has no such check.  Synthesis is scoped
        to the dual-write boundary — wire/renderer see the original id.
        """
        if elem.id:
            return elem
        # Element Protocol is opaque to dataclasses.replace's TypeVar; every
        # native element is a frozen dataclass with `id`.
        replaced = dataclasses.replace(cast("Any", elem), id=f"{elem.kind}:{index}")
        return cast("DomainElement", replaced)

    def _clear_scene(self, scene_id: SceneId) -> None:
        """Remove every element this hub owns in the given domain scene."""
        try:
            snap = self._display.snapshot(scene_id)
        except KeyError:
            return
        for element_id in snap.element_ids:
            result = self._display.apply(
                self._client_id,
                RemoveElement(scene_id=scene_id, element_id=element_id),
            )
            _warn_on_error(
                result, scene_id=scene_id, element_id=element_id, op="remove"
            )

    # Wire actions that do NOT target a scene element — emitted by display
    # chrome (menu bar, frame close button) rather than by an Element
    # renderer.  They flow through the wire event queue but have no domain
    # equivalent; the pump skips them BEFORE the element-existence check so
    # they don't trip the SFH-M1 divergence warning (Bugbot MED on PR #187).
    _NON_ELEMENT_ACTIONS: ClassVar[frozenset[str]] = frozenset({"menu", "frame_close"})

    def route_interaction(self, msg: InteractionMessage) -> None:
        """Translate a wire ``InteractionMessage`` into a domain ``Interaction``.

        PR 2: only button clicks have a corresponding domain Interaction.
        ButtonRenderer emits InteractionMessage with ``value=True`` and an
        action equal to the button's ``elem.action or elem.id``.  Display
        chrome (menu, frame close) emits InteractionMessages with no
        scene-element backing; those skip the pump entirely.  Scenes that
        don't live in the domain Display (mixed-scene case) are skipped
        silently — ``Display.interact`` would return ``UnknownElementError``
        and the warning would be noise rather than signal.  An element id
        missing from a scene the domain DOES track is the opposite — a
        divergence signal worth logging (SFH M1).

        Messages from non-button element sources (slider, checkbox, …) are
        skipped here pending their own Interaction variants in later PRs.
        """
        if msg.action in self._NON_ELEMENT_ACTIONS:
            return
        if msg.scene_id is None:
            return
        scene_id = SceneId(msg.scene_id)
        try:
            snap = self._display.snapshot(scene_id)
        except KeyError:
            return
        element_id = ElementId(msg.element_id)
        if element_id not in snap.element_ids:
            _log.warning(
                "interaction targets unknown element scene=%s element=%s",
                scene_id,
                element_id,
            )
            return
        if not self._is_button_click(msg, snap.element(element_id)):
            return
        result = self._display.interact(
            self._client_id,
            ButtonClicked(scene_id=scene_id, element_id=element_id),
        )
        _warn_on_error(result, scene_id=scene_id, element_id=element_id, op="interact")

    @staticmethod
    def _is_button_click(msg: InteractionMessage, elem: DomainElement) -> bool:
        """Return True if the wire ``InteractionMessage`` describes a button click.

        Resolution is by element kind AND wire value shape.  ButtonRenderer's
        wire-side emit always sets ``value=True`` (boolean ``True``); any
        other shape — dict (menu payload), str (input value), int — is from
        a different source and MUST NOT route as a ButtonPressed even if
        ``element_id`` happens to match a button in the scene.  Bugbot HIGH
        on PR #187 named the menu-id-collides-with-button-id case: without
        the ``msg.value is True`` guard a menu selection whose id matched a
        real button would have fired a phantom ButtonPressed to subscribers.
        """
        if elem.kind != "button":
            return False
        if msg.value is not True:
            _log.warning(
                "button interaction value=%r is not True (boolean); not a click",
                msg.value,
            )
            return False
        return True


def _warn_on_error(
    result: Result,
    *,
    scene_id: SceneId,
    element_id: ElementId,
    op: str,
) -> None:
    """Log a domain Display refusal with full context.

    Used for both ``Display.apply(...)`` (add / remove / set) and
    ``Display.interact(...)`` (button click).  The ``op`` parameter names
    the operation so the warning stays accurate as new variants land.
    """
    # The Event type alias isn't isinstance-checkable; spell the concretes.
    if isinstance(
        result, ElementAdded | ElementRemoved | ElementUpdated | ButtonPressed
    ):
        return
    _log.warning(
        "domain Display refused %s(scene=%s, element=%s): %s — %r",
        op,
        scene_id,
        element_id,
        result.kind,
        result,
    )
