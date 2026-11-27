"""RequestServer — the client's side of a relayed request (DES-107).

The Hub sends a request frame; the client's handler answers it and the answer goes
back as a reply or a refusal carrying the same request id. Each request runs as its
own task so the receive loop keeps reading and renewing the lease meanwhile.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

import pytest

from punt_lux.client.request_server import RequestRefusedError, RequestServer
from punt_lux.kernel.programmer_error import ProgrammerError
from punt_lux.wire.model.messages.relay_frames import (
    RefusalFrame,
    ReplyFrame,
    RequestFrame,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


@final
class _Connection:
    """A connection that records the text sent on it."""

    sent: list[str]
    __slots__ = ("sent",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.sent = []
        return self

    async def send(self, text: str) -> None:
        self.sent.append(text)


def _request(request_id: str = "c1.1") -> RequestFrame:
    return RequestFrame(
        request_id=request_id,
        service="terminal",
        operation="new",
        payload={"label": "build"},
    )


def _serve(server: RequestServer, frame: RequestFrame) -> _Connection:
    connection = _Connection()
    server.bind(connection)

    async def scenario() -> None:
        await server.serve(frame)

    asyncio.run(scenario())
    return connection


def test_a_handler_result_is_sent_back_as_a_reply_with_the_same_id() -> None:
    seen: list[tuple[str, str, Mapping[str, object]]] = []

    def handler(
        service: str, operation: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        seen.append((service, operation, payload))
        return {"id": "t3"}

    connection = _serve(RequestServer(handler), _request())

    assert seen == [("terminal", "new", {"label": "build"})]
    assert [ReplyFrame.model_validate_json(t) for t in connection.sent] == [
        ReplyFrame(request_id="c1.1", payload={"id": "t3"})
    ]


def test_an_async_handler_is_awaited() -> None:
    async def handler(
        _service: str, _operation: str, _payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        await asyncio.sleep(0)
        return {"ok": True}

    connection = _serve(RequestServer(handler), _request())

    assert ReplyFrame.model_validate_json(connection.sent[0]).payload == {"ok": True}


def test_a_refusal_carries_its_code_and_reason() -> None:
    def handler(_s: str, _o: str, _p: Mapping[str, object]) -> Mapping[str, object]:
        raise RequestRefusedError("not_found", "no such session")

    connection = _serve(RequestServer(handler), _request())

    assert RefusalFrame.model_validate_json(connection.sent[0]) == RefusalFrame(
        request_id="c1.1", code="not_found", reason="no such session"
    )


def test_any_other_exception_is_a_fault_with_a_fixed_reason_and_no_traceback() -> None:
    def handler(_s: str, _o: str, _p: Mapping[str, object]) -> Mapping[str, object]:
        raise RuntimeError("secret detail /Users/someone/path")

    connection = _serve(RequestServer(handler), _request())

    frame = RefusalFrame.model_validate_json(connection.sent[0])
    assert frame.code == "fault"
    assert "secret" not in frame.reason
    assert "Traceback" not in frame.reason


def test_a_client_with_no_handler_refuses_every_request_as_not_found() -> None:
    connection = _serve(RequestServer(None), _request())

    frame = RefusalFrame.model_validate_json(connection.sent[0])
    assert (frame.request_id, frame.code) == ("c1.1", "not_found")


def test_a_slow_request_does_not_block_a_second_one() -> None:
    release = asyncio.Event()

    async def handler(
        _service: str, operation: str, _payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        if operation == "slow":
            await release.wait()
        return {"op": operation}

    connection = _Connection()

    async def scenario() -> None:
        server = RequestServer(handler)
        server.bind(connection)
        slow = server.start(_request("c1.1").model_copy(update={"operation": "slow"}))
        await server.serve(_request("c1.2").model_copy(update={"operation": "fast"}))
        assert [
            ReplyFrame.model_validate_json(t).request_id for t in connection.sent
        ] == ["c1.2"]
        release.set()
        await slow

    asyncio.run(scenario())

    assert [ReplyFrame.model_validate_json(t).request_id for t in connection.sent] == [
        "c1.2",
        "c1.1",
    ]


def test_serving_before_a_connection_is_bound_is_a_programmer_error() -> None:
    server = RequestServer(lambda _s, _o, _p: {})

    async def scenario() -> None:
        await server.serve(_request())

    with pytest.raises(ProgrammerError):
        asyncio.run(scenario())


def test_a_programmer_error_in_a_handler_is_not_turned_into_a_fault_reply() -> None:
    def handler(_s: str, _o: str, _p: Mapping[str, object]) -> Mapping[str, object]:
        raise ProgrammerError("a violated invariant of the handler's own code")

    with pytest.raises(ProgrammerError):
        _serve(RequestServer(handler), _request())
