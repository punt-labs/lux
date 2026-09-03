"""The callback operations' request model.

``RegisterCallbackRequest`` is the never-raising parse of a callback a session
asks to register.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.operations.models.callback_fields import CallbackFields
from punt_lux.operations.models.common import OpError

__all__ = ["RegisterCallbackRequest"]


class RegisterCallbackRequest(BaseModel):
    """A request to register one menu callback for the caller's session.

    Holds the already-validated :class:`SessionCallback`; ``parse`` builds it
    and returns an ``OpError`` instead of raising past the adapter.
    """

    model_config = ConfigDict(frozen=True)

    callback: SessionCallback

    @classmethod
    def parse(cls, raw: CallbackFields) -> RegisterCallbackRequest | OpError:
        """Validate ``raw``, or return an ``OpError`` instead of raising."""
        try:
            callback = SessionCallback(
                id=raw.callback_id, label=raw.label, frame_id=raw.frame_id
            )
        except ValidationError as exc:
            return OpError.from_validation(exc)
        return cls(callback=callback)
