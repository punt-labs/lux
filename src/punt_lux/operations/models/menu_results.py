"""The menu read result, the set-menu request, and the generic success ack."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menus import Menu

if TYPE_CHECKING:
    from collections.abc import Sequence


__all__ = ["MenuList", "Ok", "SetMenuRequest"]


class Ok(BaseModel):
    """A capability succeeded with nothing more to report than success."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"


class MenuList(BaseModel):
    """The Hub-authoritative menu bar, read with no reach-around."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    menus: list[Menu]


class SetMenuRequest(BaseModel):
    """A request to replace the agent-defined menu bar."""

    model_config = ConfigDict(frozen=True)

    menus: list[Menu]

    @classmethod
    def parse(cls, raw: Sequence[object]) -> SetMenuRequest | OpError:
        """Build from the untyped menu list, or return an ``OpError``.

        The wire form is a list of menu dicts carrying the ``"---"`` separator
        sentinel; each is mapped through ``Menu.from_wire``, so a malformed entry
        becomes a validation error rather than a raise past the adapter.
        """
        try:
            menus = [
                Menu.from_wire(cast("Mapping[str, object]", m))
                for m in raw
                if isinstance(m, Mapping)
            ]
            return cls(menus=menus)
        except ValidationError as exc:
            return OpError.from_validation(exc)
