"""MenuEntry — the one menu entry an applet registers, and the clicks that are its.

The id a click carries back, the label the display shows, and the frame the
click raises are a single fact about the entry, so they travel as one value:
the applet owns it, and the leg registers it and recognises its clicks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.client._callback_ops import CallbackConvenienceOps
    from punt_lux.operations import Ok, OpError

__all__ = ["MenuEntry"]


@final
@dataclass(frozen=True, slots=True)
class MenuEntry:
    """A callback id, the label it appears under, and the frame a click raises."""

    callback_id: str
    label: str
    frame_id: str

    def __post_init__(self) -> None:
        for name in ("callback_id", "label", "frame_id"):
            if not getattr(self, name):
                msg = f"a menu entry's {name} is never empty"
                raise ValueError(msg)

    def register_with(self, client: CallbackConvenienceOps) -> Ok | OpError:
        """Register this entry through *client*, which reports a refusal."""
        return client.register_callback(self.callback_id, self.label, self.frame_id)

    def owns(self, callback_id: str) -> bool:
        """Say whether a click carrying *callback_id* is a click on this entry."""
        return callback_id == self.callback_id
