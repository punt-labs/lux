"""MenuAction — a clickable menu leaf that owns both halves of its wire round-trip.

A menu action is submitted UI, so this Hub-authoritative type lives in the domain
layer. It owns ``to_wire`` and the ``from_wire`` classmethod so the decode reads
every field the encode writes — including ``frame_id`` (PY-OO-5, PY-OO-7) — and it
stamps its own leaf id with the owning connection for dispatch. The ``_require_*``
staticmethods are the wire-decode primitives this leaf's decode needs.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.session_callback import MenuLeaf
from punt_lux.domain.id_separator import ID_SEPARATOR, NONBLANK_FRAME_ID

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.ids import ConnectionId

__all__ = ["MenuAction"]


class MenuAction(BaseModel):
    """A clickable menu item that fires an interaction when chosen."""

    model_config = ConfigDict(frozen=True)

    TYPE: ClassVar[str] = "action"

    kind: Literal["action"] = "action"
    id: str = Field(min_length=1)  # an id-less action is not a real state
    label: str = Field(min_length=1)  # a label-less action is not a real state
    shortcut: str | None = None  # None when the item has no accelerator
    icon: str | None = None  # None when the item has no icon
    # None when the action owns no frame to raise (the same shape
    # SessionCallback.frame_id carries): a frame-bound item BOTH raises the frame
    # Display-locally AND delivers its click, so this is a genuine optional
    # attribute, not a discriminated state (PY-TS-14, design §3.2).
    frame_id: str | None = None

    @classmethod
    def from_wire(cls, entry: Mapping[str, object], *, loc: str) -> Self:
        """Decode one agent-supplied wire item, reading every round-tripped field.

        Reads ``frame_id`` so a frame-bound agent item can raise its own frame on
        click. Both leaf keys — the ``id`` and any ``frame_id`` — are validated
        here at the agent boundary: each must be non-blank and free of the leaf-id
        separator (the same shape :class:`SessionCallback`'s fields enforce), so a
        stamped ``owner<US>key`` never splits ambiguously at dispatch. The rule
        lives on the decode, not a field validator, because the Hub itself stamps
        composite ids a validator would then wrongly refuse.
        """
        item_id = cls._require_str(entry.get("id"), loc=f"{loc}.id")
        if ID_SEPARATOR in item_id:
            msg = f"{loc}.id: must not contain the menu leaf-id separator"
            raise ValueError(msg)
        return cls(
            id=item_id,
            label=cls._require_str(entry.get("label"), loc=f"{loc}.label"),
            shortcut=cls._optional_str(entry.get("shortcut"), loc=f"{loc}.shortcut"),
            icon=cls._optional_str(entry.get("icon"), loc=f"{loc}.icon"),
            frame_id=cls._optional_frame_id(
                entry.get("frame_id"), loc=f"{loc}.frame_id"
            ),
        )

    def stamped_for(self, owner: ConnectionId) -> MenuAction:
        """Return a copy whose leaf id and frame id are owner-stamped for dispatch.

        Both keys are namespaced to the owning connection at stamp time, not at
        submit time (the agent submits raw, separator-free values):

        - the leaf ``id`` becomes a ``menu``-kind :class:`MenuLeaf` wire id, whose
          kind tag keeps it distinct from an applet-callback leaf even when a
          session owns both under the same local id, so dispatch routes it to the
          owner's inbox — never to a same-named callback;
        - a present ``frame_id`` becomes ``owner<US>frame_id`` via
          :meth:`ConnectionScopedId.compose` — the *same* primitive
          ``ScenePresentation`` composes a shown frame's key with, so a
          frame-bound item's ``frame_id`` matches the actual scene key and
          ``raise_frame`` finds it. ``None`` (no owned frame) stays ``None``.

        Copies rather than calling :meth:`from_wire`, so the composite ids are not
        refused by the boundary rule.
        """
        update: dict[str, object] = {"id": MenuLeaf("menu", owner, self.id).wire_id}
        if self.frame_id is not None:
            update["frame_id"] = ConnectionScopedId.compose(owner, self.frame_id)
        return self.model_copy(update=update)

    def to_wire(self) -> dict[str, object]:
        """Render as the untyped menu-item payload the display consumes."""
        item: dict[str, object] = {"label": self.label, "id": self.id}
        optional = {
            "shortcut": self.shortcut,
            "icon": self.icon,
            "frame_id": self.frame_id,
        }
        item.update((k, v) for k, v in optional.items() if v is not None)
        return item

    @staticmethod
    def _require_str(value: object, *, loc: str) -> str:
        """Return ``value`` when it is a non-empty string, else reject it by name."""
        if not isinstance(value, str) or not value:
            msg = f"{loc}: expected a non-empty string"
            raise ValueError(msg)
        return value

    @staticmethod
    def _optional_str(value: object, *, loc: str) -> str | None:
        """Return a present string, ``None`` when absent, or reject a non-string.

        ``None`` is the "field absent" contract of an optional wire attribute
        (shortcut, icon), not a give-up (PY-TS-14).
        """
        if value is None:
            return None
        if not isinstance(value, str):
            msg = f"{loc}: expected a string"
            raise ValueError(msg)
        return value

    @staticmethod
    def _optional_frame_id(value: object, *, loc: str) -> str | None:
        """Return a present, non-blank, separator-free frame id, or ``None``.

        A present frame id names a frame to raise, so it must be a real leaf key —
        the same non-blank, separator-free shape :attr:`SessionCallback.frame_id`
        enforces (the shared :data:`NONBLANK_FRAME_ID` pattern), checked at the
        agent boundary because the Hub stamps composite ids a field validator would
        refuse. ``None`` is the documented "no owned frame" state (PY-TS-14).
        """
        frame_id = MenuAction._optional_str(value, loc=loc)
        if frame_id is not None and re.match(NONBLANK_FRAME_ID, frame_id) is None:
            msg = f"{loc}: must be non-blank and free of the leaf-id separator"
            raise ValueError(msg)
        return frame_id
