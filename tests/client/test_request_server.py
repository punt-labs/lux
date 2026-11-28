"""RequestServer — the client's side of a relayed request (DES-107).

The Hub sends a request frame; the client's handler answers it and the answer goes
back as a reply or a refusal carrying the same request id. Each request runs as its
own task so the receive loop keeps reading and renewing the lease meanwhile.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Self, cast, final

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


def test_a_blocking_sync_handler_does_not_stall_the_event_loop() -> None:
    release = threading.Event()
    connection = _Connection()

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        started = asyncio.Event()

        def handler(
            _service: str, operation: str, _payload: Mapping[str, object]
        ) -> Mapping[str, object]:
            if operation == "slow":
                loop.call_soon_threadsafe(started.set)
                release.wait(timeout=10)  # blocking I/O in a plain function
            return {"op": operation}

        server = RequestServer(handler)
        server.bind(connection)
        slow = server.start(_request("c1.1").model_copy(update={"operation": "slow"}))
        # Wait for the slow handler to start, or for its request to end without
        # starting it; no thread and no deadline.
        started_wait = asyncio.ensure_future(started.wait())
        await asyncio.wait({slow, started_wait}, return_when=asyncio.FIRST_COMPLETED)
        started_wait.cancel()
        assert started.is_set()
        # The loop is free: a second request is answered while the first blocks.
        await server.serve(_request("c1.2").model_copy(update={"operation": "fast"}))
        assert [
            ReplyFrame.model_validate_json(t).request_id for t in connection.sent
        ] == ["c1.2"]
        release.set()
        await slow

    asyncio.run(scenario())


def test_an_async_handler_runs_on_the_event_loop_and_can_start_tasks() -> None:
    async def handler(
        _service: str, operation: str, _payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        async def answer() -> Mapping[str, object]:
            return {"op": operation}

        return await asyncio.get_running_loop().create_task(answer())

    connection = _serve(RequestServer(handler), _request())

    frame = ReplyFrame.model_validate_json(connection.sent[0])
    assert frame.payload == {"op": "new"}


def test_a_sync_handler_runs_in_a_worker_thread_not_on_the_loop() -> None:
    seen: list[bool] = []

    def handler(
        _service: str, _operation: str, _payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            seen.append(False)  # no running loop: a worker thread
        else:
            seen.append(True)
        return {}

    _serve(RequestServer(handler), _request())

    assert seen == [False]


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


def test_a_reply_that_cannot_be_serialized_is_a_fault_not_a_silence() -> None:
    def handler(_s: str, _o: str, _p: Mapping[str, object]) -> Mapping[str, object]:
        return {"bad": object()}

    connection = _serve(RequestServer(handler), _request())

    frame = RefusalFrame.model_validate_json(connection.sent[0])
    assert frame.code == "fault"
    assert frame.request_id == "c1.1"


def test_a_reply_that_is_not_a_mapping_is_a_fault_not_a_silence() -> None:
    def handler(_s: str, _o: str, _p: Mapping[str, object]) -> Mapping[str, object]:
        return cast("Mapping[str, object]", 42)

    connection = _serve(RequestServer(handler), _request())

    frame = RefusalFrame.model_validate_json(connection.sent[0])
    assert frame.code == "fault"


def test_a_failed_request_task_is_logged_not_left_unretrieved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(_s: str, _o: str, _p: Mapping[str, object]) -> Mapping[str, object]:
        raise ProgrammerError("a violated invariant of the handler's own code")

    server = RequestServer(handler)
    server.bind(_Connection())

    async def scenario() -> None:
        task = server.start(_request())
        await asyncio.wait({task})
        await asyncio.sleep(0)

    with caplog.at_level("ERROR"):
        asyncio.run(scenario())

    assert any("c1.1" in record.getMessage() for record in caplog.records)
