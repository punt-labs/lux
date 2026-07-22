"""The one discriminated-result to HTTP mapping every REST route shares.

A route binds a request, calls one operation, and hands the typed result here.
:class:`HttpErrorMap` turns an :class:`OpError` into the matching HTTP status by
its ``code`` — the single table so every route reports a failure the same way —
and passes a success result straight through. ``code`` is a closed
:data:`OpErrorCode` set, so a new code with no mapping raises loudly at the one
place instead of degrading silently at each call site.
"""

from __future__ import annotations

from typing import ClassVar, Self, final

from fastapi import HTTPException

from punt_lux.operations.models.common import OpError, OpErrorCode

__all__ = ["HttpErrorMap"]


@final
class HttpErrorMap:
    """Map an ``OpError`` to its HTTP status; pass a success result through."""

    # The single failure table. The design fixes each code's status: a request
    # the schema rejects and a write the Hub refuses are both the caller's fault
    # (422, 409); an absent resource is 404; an unreachable or slow display is a
    # gateway timeout/unavailable (503, 504); a backing resource that failed a
    # valid request — a malformed display reply, config-file I/O — is a bad
    # gateway (502). FastAPI's own body-binding raises the 422 for a malformed
    # request before an operation runs; these are the semantic errors.
    _STATUS: ClassVar[dict[OpErrorCode, int]] = {
        "invalid_request": 422,
        "not_found": 404,
        "rejected": 409,
        "fault": 502,
        "display_unavailable": 503,
        "timeout": 504,
    }

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def status_for(self, code: OpErrorCode) -> int:
        """Return the HTTP status a given ``OpError`` code maps to."""
        return self._STATUS[code]

    def respond[T](self, result: T | OpError) -> T:
        """Return a success result, or raise the error's HTTP status.

        An ``OpError``'s ``reason`` becomes a ``detail`` **string** (the OpenAPI
        spec allows ``detail`` to be a string or a list). This is deliberately a
        different 422 body from FastAPI's own request-binding rejection, whose
        ``detail`` is a **list** of ``{loc, msg, type}`` objects: a malformed body
        or query is caught by FastAPI before the operation runs and keeps its
        located-list shape, while a semantic ``invalid_request`` the operation
        returns (a bad repo, an out-of-range value it validated) carries the bare
        reason string. Both are 422; the shapes differ by which layer rejected.
        """
        if isinstance(result, OpError):
            raise HTTPException(
                status_code=self._STATUS[result.code], detail=result.reason
            )
        return result
