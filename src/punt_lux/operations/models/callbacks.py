"""The callback operations' request model.

``RegisterCallbackRequest`` is the never-raising parse of a callback a session
asks to register.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.operations.models.common import OpError

__all__ = ["RegisterCallbackRequest"]


class RegisterCallbackRequest(BaseModel):
    """A request to register one menu callback for the caller's session.

    Holds the already-validated :class:`SessionCallback`; ``parse`` builds it and
    returns an ``OpError`` instead of raising past the adapter — the never-raising
    contract every request model holds. A malformed id (empty, or carrying the
    leaf-id separator) or label is reported by field name.
    """

    model_config = ConfigDict(frozen=True)

    callback: SessionCallback

    @classmethod
    def parse(
        cls, *, callback_id: str, label: str
    ) -> RegisterCallbackRequest | OpError:
        """Validate the callback, or return an ``OpError`` instead of raising."""
        try:
            return cls(callback=SessionCallback(id=callback_id, label=label))
        except ValidationError as exc:
            return OpError.from_validation(exc)
