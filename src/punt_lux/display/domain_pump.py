"""Dual-write pump: mirror native-kind SceneMessages into the domain Display."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, ClassVar, Self, cast

from punt_lux.domain.composite import Composite
from punt_lux.domain.display import Display, Result
from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.event import (
    ElementAdded,
    ElementRemoved,
    ElementUpdated,
)
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.update import AddElement, RemoveElement
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.text import TextElement

__all__ = ["DomainPump"]

_log = logging.getLogger(__name__)

# ABC-based element kinds that route through the ``apply`` path.
# ABC elements carry runtime state (renderer factory, emit, handler
# registry) and cannot pass through dataclasses.replace, which the basic
# native-kind path uses for anonymous-id synthesis.
_ABC_TYPES: tuple[type, ...] = (
    TextElement,
    ButtonElement,
    CheckboxElement,
    DialogElement,
)


class DomainPump:
    """Mirror native-kind SceneMessages into a domain Display.

    "Native" = element kinds with their own per-class renderer in
    ``display.renderers`` — currently the six basics (Text, Image,
    Separator, Progress, Spinner, Markdown) plus the nine inputs (Button,
    Slider, Checkbox, Combo, InputText, InputNumber, Radio, ColorPicker,
    Selectable).

    A scene containing only native kinds is routed through ``Display.apply``;
    a scene containing any non-native kind is skipped (mixed-scene rule —
    SceneManager owns those families until they too gain native renderers).
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
        # while SceneManager drops them.
        if any(not isinstance(elem, self._native_kinds) for elem in msg.elements):
            return
        scene_id = SceneId(msg.id)
        self._display.add_scene(scene_id)
        self._clear_scene(scene_id)
        for index, elem in enumerate(msg.elements):
            # cast: isinstance check above narrowed the element to a native
            # kind, every one of which satisfies the domain Element Protocol.
            domain_elem = self._with_unique_id(cast("DomainElement", elem), index=index)
            self._install_subtree(scene_id, domain_elem, parent_id=None)

    def _install_subtree(
        self,
        scene_id: SceneId,
        element: DomainElement,
        *,
        parent_id: ElementId | None,
    ) -> None:
        """Apply AddElement for ``element``, then recurse into composites.

        Composite Elements expose ``children`` (structural Protocol);
        every child resolves through the same ``Display.apply`` gate so
        click resolution on a dialog's child Button finds it in the
        Display's index. Non-composite elements have no children — the
        ``isinstance(Composite)`` branch is skipped.
        """
        result = self._display.apply(
            self._client_id,
            AddElement(
                scene_id=scene_id,
                element=element,
                parent_id=parent_id,
            ),
        )
        _warn_on_error(
            result,
            scene_id=scene_id,
            element_id=ElementId(element.id),
            op="add",
        )
        if isinstance(element, Composite):
            element_id = ElementId(element.id)
            for child in element.children:
                self._install_subtree(scene_id, child, parent_id=element_id)

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
        if isinstance(elem, _ABC_TYPES):
            msg = (
                f"ABC element of kind={elem.kind!r} requires an explicit id "
                "(anonymous-id synthesis only supports dataclass elements)"
            )
            raise ValueError(msg)
        # Element Protocol is opaque to dataclasses.replace's TypeVar; every
        # native dataclass element is a frozen dataclass with `id`.
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
    # renderer.  They flow through the wire event queue but have no
    # corresponding scene element; the pump drops them before invoking
    # ``Display.interact``.
    _NON_ELEMENT_ACTIONS: ClassVar[frozenset[str]] = frozenset({"menu", "frame_close"})

    # route_interaction removed by D21: the display no longer dispatches
    # interactions locally. The remote_dispatch handler on each element
    # sends RemoteEventHandlerInvocations to the Hub, where the real handler fires.


def _warn_on_error(
    result: Result,
    *,
    scene_id: SceneId,
    element_id: ElementId,
    op: str,
) -> None:
    """Log a domain Display refusal with full context for ``apply`` results."""
    if isinstance(result, ElementAdded | ElementRemoved | ElementUpdated):
        return
    _log.warning(
        "domain Display refused %s(scene=%s, element=%s): %s — %r",
        op,
        scene_id,
        element_id,
        result.kind,
        result,
    )
