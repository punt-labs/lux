"""MenuAction — a clickable menu leaf that owns both halves of its wire round-trip.

A menu action is submitted UI, so this Hub-authoritative type lives in the domain
layer. It owns ``to_wire`` and the ``from_wire`` classmethod so the decode reads
every field the encode writes — including ``frame_id`` (PY-OO-5, PY-OO-7) — and it
stamps its own leaf id with the owning connection for dispatch. The ``_require_*``
staticmethods are the wire-decode primitives this leaf's decode needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.domain.id_separator import ID_SEPARATOR

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

        Reads ``frame_id`` — the byproduct that lets a frame-bound agent item raise
        its frame on click (gap a). The id is rejected here, at the agent boundary,
        if it carries the leaf-id separator, so a stamped ``owner<US>id`` never
        splits ambiguously at dispatch. The rule lives on the decode, not a field
        validator, because the Hub itself stamps composite ids a validator would
        then wrongly refuse.
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
            frame_id=cls._optional_str(entry.get("frame_id"), loc=f"{loc}.frame_id"),
        )

    def stamped_for(self, owner: ConnectionId) -> MenuAction:
        """Return a copy whose leaf id is stamped ``owner<US>id`` for dispatch.

        Uses the one leaf-id encoding the callback path uses
        (:class:`CallbackInvocation`), so an agent item's click round-trips to the
        owning session exactly as a callback leaf does — the shared ownership
        stamping both menu families rely on. Copies rather than calling
        :meth:`from_wire`, so the composite id is not refused by the boundary rule.
        """
        stamped = CallbackInvocation(owner, self.id).menu_id
        return self.model_copy(update={"id": stamped})

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
        (shortcut, icon, frame_id), not a give-up (PY-TS-14).
        """
        if value is None:
            return None
        if not isinstance(value, str):
            msg = f"{loc}: expected a string"
            raise ValueError(msg)
        return value
