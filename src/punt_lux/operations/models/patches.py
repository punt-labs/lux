"""The update request — a batch of element patches for one scene."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["UpdateRequest"]


class UpdateRequest(BaseModel):
    """A batch of element patches. Their shape is the writer's contract.

    Each patch is a wire mapping — ``{"id", "set"}`` or ``{"id", "remove"}``.
    The per-patch shape is validated once, whole, by ``HubSceneWriter`` inside
    the operation, which owns the exact rejection wording; modelling the patch
    body here would duplicate that authority (PY-TS-14 wire boundary).
    """

    patches: list[dict[str, object]]

    @classmethod
    def parse(cls, raw_patches: Sequence[object]) -> UpdateRequest | OpError:
        """Wrap the patch list, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate({"patches": list(raw_patches)})
        except ValidationError as exc:
            return OpError(code="invalid_request", reason=exc.errors()[0]["msg"])
