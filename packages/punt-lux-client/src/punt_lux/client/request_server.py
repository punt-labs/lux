"""RequestServer — a client's answers to the typed requests the Hub relays to it.

The Hub sends a :class:`~punt_lux.wire.model.messages.relay_frames.RequestFrame`
down the listen leg (DES-107). The client's handler receives ``(service,
operation, payload)`` and returns the reply payload, or raises
:class:`RequestRefusedError` with a code and reason. Any other exception becomes a
``fault`` with a fixed reason that carries no traceback, so a client's internals
never cross the wire. Each request runs as its own task: the receive loop keeps
reading, and renewing the lease, while a request is served.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast, final

from punt_lux.kernel.programmer_error import ProgrammerError
from punt_lux.wire.model.messages.relay_frames import (
    RefusalFrame,
    ReplyFrame,
    RequestFrame,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

__all__ = ["RequestHandler", "RequestRefusedError", "RequestServer"]

logger = logging.getLogger(__name__)

type RequestHandler = Callable[
    [str, str, Mapping[str, object]],
    Awaitable[Mapping[str, object]] | Mapping[str, object],
]
"""Answer one relayed request: ``(service, operation, payload)`` to a reply payload."""

_FAULT_REASON = "the provider failed while serving the request"
_NO_HANDLER_REASON = "this client serves no requests"


class RequestRefusedError(Exception):
    """Refuse a request with a category the caller can act on.

    The category and reason travel as the exception's ``args``, so the class holds
    no state of its own.
    """

    @property
    def code(self) -> Literal["rejected", "invalid_request", "not_found", "fault"]:
        """The refusal category the caller can act on."""
        return cast(
            "Literal['rejected', 'invalid_request', 'not_found', 'fault']", self.args[0]
        )

    @property
    def reason(self) -> str:
        """The refusal's reason, in words for the caller."""
        return str(self.args[1])


class _Sender(Protocol):
    """The one method of a connection the server needs."""

    async def send(self, text: str, /) -> None:
        """Send one text frame."""
        ...


@final
class RequestServer:
    """Serve relayed requests with one handler, each as its own task."""

    _connection: _Sender | None
    _handler: RequestHandler | None
    _tasks: set[asyncio.Task[None]]
    __slots__ = ("_connection", "_handler", "_tasks")

    def __new__(cls, handler: RequestHandler | None) -> Self:
        self = super().__new__(cls)
        self._connection = None
        self._handler = handler
        self._tasks = set()
        return self

    def bind(self, connection: _Sender) -> None:
        """Answer on ``connection`` from now on; a session binds its own."""
        self._connection = connection

    def start(self, frame: RequestFrame) -> asyncio.Task[None]:
        """Serve ``frame`` as a task and return it; the receive loop does not wait."""
        task = asyncio.ensure_future(self.serve(frame))
        task.set_name(frame.request_id)
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task[None]) -> None:
        """Forget a finished task, and log a failure nothing else would observe."""
        self._tasks.discard(task)
        if task.cancelled():
            return
        failure = task.exception()
        if failure is not None:
            logger.error(
                "relayed request %s failed unrecoverably",
                task.get_name(),
                exc_info=failure,
            )

    async def serve(self, frame: RequestFrame) -> None:
        """Answer ``frame`` on the bound connection with a reply or a refusal."""
        answer = await self._answer(frame)
        if self._connection is None:
            msg = "a request server answers only on a bound connection"
            raise ProgrammerError(msg)
        await self._connection.send(answer)

    def cancel_all(self) -> None:
        """Cancel the requests still in flight when the session ends."""
        for task in tuple(self._tasks):
            task.cancel()

    async def _answer(self, frame: RequestFrame) -> str:
        """Return the frame to send: a reply, or a refusal when serving failed."""
        if self._handler is None:
            return RefusalFrame(
                request_id=frame.request_id, code="not_found", reason=_NO_HANDLER_REASON
            ).model_dump_json()
        try:
            result = self._handler(frame.service, frame.operation, frame.payload)
            if inspect.isawaitable(result):
                result = await result
        except RequestRefusedError as refusal:
            return RefusalFrame(
                request_id=frame.request_id, code=refusal.code, reason=refusal.reason
            ).model_dump_json()
        except ProgrammerError:
            raise
        except Exception:
            logger.exception(
                "request %s (%s.%s) failed",
                frame.request_id,
                frame.service,
                frame.operation,
            )
            return self._fault(frame)
        try:
            return ReplyFrame(
                request_id=frame.request_id, payload=dict(result)
            ).model_dump_json()
        except (TypeError, ValueError):
            logger.exception(
                "request %s (%s.%s) returned a reply that cannot be sent",
                frame.request_id,
                frame.service,
                frame.operation,
            )
            return self._fault(frame)

    @staticmethod
    def _fault(frame: RequestFrame) -> str:
        return RefusalFrame(
            request_id=frame.request_id, code="fault", reason=_FAULT_REASON
        ).model_dump_json()
