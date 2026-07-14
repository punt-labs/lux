"""InteractionEventBuilder — map an element kind + wire value to a typed event.

The in-process Hub double (``Display.interact``) resolves an element and a wire
value, then needs the typed interaction event that element's kind fires:
``button`` → ``ButtonClicked``, ``checkbox`` / ``input_text`` → ``ValueChanged``,
``collapsing_header`` → ``HeaderToggled``, ``tab_bar`` → ``TabChanged``. The
value must have the shape that kind carries or the interaction is rejected with
``WrongKindError`` (PY-EH-1). Housing that decision here keeps ``display.py``
focused on the store + dispatch orchestration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.domain.container_interaction import HeaderToggled, TabChanged
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.interaction_errors import WrongKindError

if TYPE_CHECKING:
    from punt_lux.domain.element import Element
    from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["InteractionEventBuilder", "TypedInteraction"]

type TypedInteraction = ButtonClicked | ValueChanged | HeaderToggled | TabChanged


class InteractionEventBuilder:
    """Construct the typed interaction event for an element kind + wire value.

    Stateless — one shared instance suffices. Each per-kind method validates the
    value's shape at the boundary and constructs the event; an unrecognized kind
    or a wrong-shaped value raises ``WrongKindError``.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def build(
        self,
        *,
        element: Element,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> TypedInteraction:
        """Return the typed event ``element``'s kind fires for ``value``."""
        kind = element.kind
        if kind == "button":
            return self._button(scene_id, element_id, owner_id, value)
        if kind in ("checkbox", "input_text"):
            return self._value_changed(kind, scene_id, element_id, owner_id, value)
        if kind == "collapsing_header":
            return self._header_toggled(scene_id, element_id, owner_id, value)
        if kind == "tab_bar":
            return self._tab_changed(scene_id, element_id, owner_id, value)
        raise WrongKindError(
            scene_id=scene_id,
            element_id=element_id,
            expected="button, checkbox, input_text, collapsing_header, or tab_bar",
            got=kind,
        )

    @staticmethod
    def _button(
        scene_id: SceneId, element_id: ElementId, owner_id: ClientId, value: object
    ) -> ButtonClicked:
        if value is not True:
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected="button click (value is True)",
                got=f"value={value!r}",
            )
        return ButtonClicked(
            scene_id=scene_id, element_id=element_id, owner_id=owner_id
        )

    @staticmethod
    def _value_changed(
        kind: str,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> ValueChanged:
        # A checkbox toggle carries ``bool``; an input_text edit carries ``str``.
        want_bool = kind == "checkbox"
        matches = isinstance(value, bool) if want_bool else isinstance(value, str)
        if not matches or not isinstance(value, bool | str):
            expected = "bool" if want_bool else "str"
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected=f"{kind} value ({expected})",
                got=f"value={value!r}",
            )
        return ValueChanged(
            scene_id=scene_id, element_id=element_id, owner_id=owner_id, value=value
        )

    @staticmethod
    def _header_toggled(
        scene_id: SceneId, element_id: ElementId, owner_id: ClientId, value: object
    ) -> HeaderToggled:
        if not isinstance(value, bool):
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected="collapsing_header toggle (bool value)",
                got=f"value={value!r}",
            )
        return HeaderToggled(
            scene_id=scene_id, element_id=element_id, owner_id=owner_id, open_=value
        )

    @staticmethod
    def _tab_changed(
        scene_id: SceneId, element_id: ElementId, owner_id: ClientId, value: object
    ) -> TabChanged:
        if not isinstance(value, str):
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected="tab change (str tab_id)",
                got=f"value={value!r}",
            )
        return TabChanged(
            scene_id=scene_id, element_id=element_id, owner_id=owner_id, tab_id=value
        )
