"""RestReply — read one HTTP response into a typed result or a mapped OpError.

The client sends a request and gets back a status and bytes; turning those into
the operation's success model or an :class:`OpError` is a job of its own, so it
lives here rather than in the client's send path. RestReply owns the inverse of
the REST error table and the one subtlety the client should not carry: a 2xx whose
body is not the expected model is a fault — a stale ephemeral port answered by a
foreign server — not a success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from pydantic import BaseModel, ValidationError

from punt_lux.operations import OpError
from punt_lux.rest_error_body import ErrorBody

if TYPE_CHECKING:
    from punt_lux.operations.models.common import OpErrorCode
    from punt_lux.rest_transport import HttpResponse

__all__ = ["RestReply"]

# The inverse of the REST error table (rest/status.py maps code -> status), read
# from the client's end; an unmapped status is a fault.
_CODE_BY_STATUS: dict[int, OpErrorCode] = {
    401: "identification_required",
    404: "not_found",
    409: "rejected",
    422: "invalid_request",
    502: "fault",
    503: "display_unavailable",
    504: "timeout",
}


@final
class RestReply:
    """One HTTP response from luxd, read as the expected model or a mapped error."""

    _response: HttpResponse
    __slots__ = ("_response",)

    def __new__(cls, response: HttpResponse) -> Self:
        self = super().__new__(cls)
        self._response = response
        return self

    def read[T: BaseModel](self, ok: type[T]) -> T | OpError:
        """Return the reply parsed as ``ok``, or the mapped ``OpError``.

        A 2xx whose body is not ``ok`` is defended like the error path — not with a
        traceback — and its reason names a short body preview so a wrong server on a
        stale port is recognizable rather than guessed at.
        """
        response = self._response
        if 200 <= response.status < 300:
            try:
                return ok.model_validate_json(response.body)
            except ValidationError:
                snippet = ErrorBody(response.body).snippet()
                tail = f": {snippet}" if snippet else ""
                return OpError(
                    code="fault",
                    reason=f"luxd returned an unexpected {response.status} body{tail}",
                )
        return OpError(
            code=_CODE_BY_STATUS.get(response.status, "fault"),
            reason=ErrorBody(response.body).reason(response.status),
        )
