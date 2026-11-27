"""An operation's failure as an HTTP response that names its exact code.

Several codes share a status (a lost provider and a fault are both 502, an
unavailable provider and an unavailable display both 503), so the status alone
cannot name the code. :class:`OpFailureError` carries the status, code and reason as
its ``args``, and :class:`OpErrorHandler` writes the code into the response body
beside the reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

__all__ = ["OpErrorHandler", "OpFailureError"]


class OpFailureError(Exception):
    """Fail a route with ``(status, code, reason)``; the app's handler renders it."""

    @property
    def status(self) -> int:
        """The HTTP status the failure maps to."""
        return cast("int", self.args[0])

    @property
    def code(self) -> str:
        """The operation's exact error code."""
        return str(self.args[1])

    @property
    def reason(self) -> str:
        """The operation's reason, without surface wording."""
        return str(self.args[2])


@final
class OpErrorHandler:
    """Render an :class:`OpFailureError` as ``{"detail": reason, "code": code}``.

    ``detail`` stays the bare reason string, so a client that reads only the
    detail is unaffected; a client that reads ``code`` gets the exact code.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def install(self, app: FastAPI) -> None:
        """Register the handler on ``app``."""
        app.add_exception_handler(OpFailureError, self._respond)

    @staticmethod
    async def _respond(_request: Request, exc: Exception) -> JSONResponse:
        failure = cast("OpFailureError", exc)
        return JSONResponse(
            {"detail": failure.reason, "code": failure.code},
            status_code=failure.status,
        )
