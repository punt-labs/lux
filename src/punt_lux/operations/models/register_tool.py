"""The register-tool request — a never-raising parse of one Tools-menu item."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from punt_lux.domain.hub.menu_models import MenuAction
from punt_lux.operations.models.common import OpError

__all__ = ["RegisterToolRequest"]


class RegisterToolRequest(BaseModel):
    """A request to register one item in the shared Tools menu.

    ``tool_id`` carries the same non-empty invariant ``MenuAction.id`` requires,
    validated here against the tool's own parameter name so a bad id is reported
    as ``tool_id: ...`` — and ``parse`` returns an ``OpError`` instead of raising
    past the adapter, the never-raising contract every request model holds.
    """

    model_config = ConfigDict(frozen=True)

    tool_id: str = Field(min_length=1)  # an id-less tool item is not a real state
    label: str = Field(min_length=1)  # a label-less tool item is not a real state
    shortcut: str | None = None  # None when the item has no accelerator
    icon: str | None = None  # None when the item has no icon

    @classmethod
    def parse(
        cls, *, tool_id: str, label: str, shortcut: str | None, icon: str | None
    ) -> RegisterToolRequest | OpError:
        """Validate the tool item, or return an ``OpError`` instead of raising."""
        try:
            return cls(tool_id=tool_id, label=label, shortcut=shortcut, icon=icon)
        except ValidationError as exc:
            return OpError.from_validation(exc)

    def to_action(self) -> MenuAction:
        """Render as the domain ``MenuAction``; the id is already validated."""
        return MenuAction(
            id=self.tool_id, label=self.label, shortcut=self.shortcut, icon=self.icon
        )
