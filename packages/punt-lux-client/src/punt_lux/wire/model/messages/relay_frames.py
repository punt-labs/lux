"""The request, reply and refusal frames of the listen leg (DES-107).

The Hub sends a :class:`RequestFrame` down the leg to the client that serves the
named service; the client answers with a :class:`ReplyFrame` or a
:class:`RefusalFrame` carrying the same ``request_id``. The leg's other frames
live in :mod:`punt_lux.wire.model.messages.listen`, which unions these in.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = ["RefusalCode", "RefusalFrame", "ReplyFrame", "RequestFrame"]


class RequestFrame(BaseModel):
    """A typed request the Hub relays to the client that serves ``service``.

    The ``request_id`` is minted by the Hub and never reused, so a late reply
    cannot satisfy a different request.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["request"] = "request"
    request_id: str
    service: str
    operation: str
    # The operation's request; a wire boundary, typed models at both ends.
    payload: dict[str, object]


class ReplyFrame(BaseModel):
    """A client's answer to a :class:`RequestFrame`, matched by ``request_id``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["reply"] = "reply"
    request_id: str
    # The operation's reply; the wire boundary keeps it ``object``-valued and the
    # caller parses it into the operation's own typed model.
    payload: dict[str, object]


RefusalCode = Literal["rejected", "invalid_request", "not_found", "fault"]
_REFUSAL_CODES: tuple[str, ...] = ("rejected", "invalid_request", "not_found", "fault")


class RefusalFrame(BaseModel):
    """A client's refusal of a :class:`RequestFrame`, with a category and a reason.

    ``rejected``, ``invalid_request`` and ``not_found`` say nothing executed;
    ``fault`` says the outcome is unknown. A code outside the four reads as
    ``fault`` so an unknown value never fails validation.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["refusal"] = "refusal"
    request_id: str
    code: RefusalCode
    reason: str

    @field_validator("code", mode="before")
    @classmethod
    def _unknown_is_fault(cls, value: object) -> object:
        return value if isinstance(value, str) and value in _REFUSAL_CODES else "fault"
