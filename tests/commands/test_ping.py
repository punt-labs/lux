"""Direct tests for :class:`PingCommand` -- Humble Object testing (PL-TT-5).

An in-memory :class:`Ctx` with a stub :class:`OpsPort` exercises the command
without spawning luxd, without HTTP, and without an MCP session. The cases
cover success, the two shipped error status lines the MCP surface has always
emitted, and the ``wait=None`` default forwarding contract every adapter
relies on.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import Ctx, PingOps, ping
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.operations import OpError, Pong

if TYPE_CHECKING:
    from punt_lux.commands._result import CommandResult
    from punt_lux.operations.models.common import OpErrorCode


@final
class _StubOps:
    """A stub ``OpsPort`` that returns one preset ping result and captures the wait."""

    _result: Pong | OpError
    _forwarded_wait: float | None
    _called: bool
    __slots__ = ("_called", "_forwarded_wait", "_result")

    def __new__(cls, result: Pong | OpError) -> Self:
        self = super().__new__(cls)
        self._result = result
        self._forwarded_wait = None
        self._called = False
        return self

    def ping(self, wait: float | None = None) -> Pong | OpError:
        self._forwarded_wait = wait
        self._called = True
        return self._result

    @property
    def forwarded_wait(self) -> float | None:
        return self._forwarded_wait

    @property
    def called(self) -> bool:
        return self._called


def _identity() -> ClientIdentity:
    """Build a headless CLI identity -- PingCommand does not read it."""
    return ClientIdentity(kind="cli", name="test")


def _run(
    result: Pong | OpError, wait: float | None = None
) -> tuple[CommandResult, _StubOps]:
    """Build a Ctx around *result*, drive the command, and return both."""
    ops = _StubOps(result)
    ctx: Ctx[PingOps] = Ctx(ops=ops, identity=_identity())
    return asyncio.run(ping(ctx, wait)), ops


def test_ping_success_renders_shipped_text_and_structured_envelope() -> None:
    result, _ = _run(Pong(rtt_seconds=0.042), wait=0.5)

    assert result.text == "pong rtt=0.042s"
    assert result.json_data == {"rtt_seconds": 0.042}
    assert result.error is False
    assert result.exit_code == 0


def test_ping_fault_renders_generic_error_line() -> None:
    result, _ = _run(OpError(code="fault", reason="malformed reply"))

    assert result.text == "error: malformed reply"
    assert result.error is True
    assert result.exit_code == 1


def test_ping_timeout_renders_timeout_line() -> None:
    result, _ = _run(OpError(code="timeout", reason="slow display"), wait=1.0)

    assert result.text == "timeout"
    assert result.error is True
    assert result.exit_code == 1


def test_ping_wait_none_forwards_none_to_ops() -> None:
    _, ops = _run(Pong(rtt_seconds=0.001))

    assert ops.called
    assert ops.forwarded_wait is None


def test_ping_display_unavailable_renders_not_running() -> None:
    """The shipped MCP tool's ``not running`` line is preserved through the command."""
    code: OpErrorCode = "display_unavailable"
    result, _ = _run(OpError(code=code, reason="display down"))

    assert result.text == "not running"
    assert result.error is True


def test_execute_returns_the_typed_pong_with_no_envelope() -> None:
    ops = _StubOps(Pong(rtt_seconds=0.017))
    ctx: Ctx[PingOps] = Ctx(ops=ops, identity=_identity())

    result = asyncio.run(ping.execute(ctx))

    assert result == Pong(rtt_seconds=0.017)


def test_execute_returns_the_typed_op_error_with_no_envelope() -> None:
    ops = _StubOps(OpError(code="timeout", reason="slow display"))
    ctx: Ctx[PingOps] = Ctx(ops=ops, identity=_identity())

    result = asyncio.run(ping.execute(ctx))

    assert result == OpError(code="timeout", reason="slow display")


def test_call_renders_execute_into_the_shared_envelope() -> None:
    # __call__ is execute() plus the rendering __call__ layers on top -- this
    # pins that relationship so a future change to one cannot silently drift
    # from the other.
    ops = _StubOps(Pong(rtt_seconds=0.017))
    ctx: Ctx[PingOps] = Ctx(ops=ops, identity=_identity())

    result = asyncio.run(ping(ctx))

    assert result.text == "pong rtt=0.017s"
    assert result.json_data == {"rtt_seconds": 0.017}
