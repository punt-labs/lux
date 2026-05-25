"""``ButtonClicked`` — the validated typed event a button-click produces.

``ButtonClicked`` is the canonical io-model event for a button press. The
class has exactly one construction site — ``Display.interact`` — enforced
by a factory-token guard on ``__new__``. Direct construction outside that
boundary raises ``TypeError``.

Upstream of ``Display.interact`` lives wire-shape triage in the pump;
downstream lives typed handler dispatch through ``Element.fire``. No
intermediate sum type stands between the inbound ``RemoteEventHandlerInvocation``
and the ``ButtonClicked`` the dispatcher hands to the per-Element handler
registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["ButtonClicked"]


# Module-private sentinel — the single object ``ButtonClicked.__new__``
# accepts as proof of legitimate construction. ``Display.interact`` is the
# one caller authorized to pass this; tests that need a ``ButtonClicked``
# without standing up a full ``Display`` may import it but the leading
# underscore in the alias-form keeps that path visible at audit time.
BUTTON_CLICKED_TOKEN: object = object()


@dataclass(frozen=True, slots=True, init=False)
class ButtonClicked:
    """A validated button click. Constructible ONLY through the factory token.

    The frozen-slots dataclass holds the three identifying fields plus a
    ``kind`` discriminator. ``init=False`` disables the synthesized
    ``__init__`` so ``__new__`` is the only construction path; field
    writes go through ``object.__setattr__`` because the synthesized
    ``__setattr__`` raises ``FrozenInstanceError`` after construction.
    """

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    kind: ClassVar[Literal["button_clicked"]] = "button_clicked"

    def __new__(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        _token: object,
    ) -> Self:
        if _token is not BUTTON_CLICKED_TOKEN:
            msg = (
                "ButtonClicked must be constructed by Display.interact; "
                "direct construction is not allowed"
            )
            raise TypeError(msg)
        # ``object.__new__`` (not ``super().__new__``) avoids the
        # dataclass(slots=True) re-class quirk: the synthesized slots
        # class is a distinct object from the one the __class__ cell
        # captured at method-definition time, so super() resolves with
        # the old type and rejects the new cls argument.
        self = object.__new__(cls)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "element_id", element_id)
        object.__setattr__(self, "owner_id", owner_id)
        return self
