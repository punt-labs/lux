"""A daemon exchange that answers new, list and kill from a scripted session list."""

from __future__ import annotations

from typing import Self

from punt_lux.pty.daemon_exchange import RetryableRefusalError, SessionRefusedError
from punt_lux.wire.stream.control import ControlRequest
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.replies import SuccessReply
from punt_lux.wire.stream.session_requests import KillRequest, ListRequest


class FakeDaemon:
    """Hand out ``sessions`` in order; ``running`` says whether they still run."""

    _sessions: list[str]
    _started: list[str]
    _killed: list[str]
    _refusal: str
    _retryable: bool
    _kill_refusal: SessionRefusedError | None
    running: bool

    def __new__(cls, *sessions: str) -> Self:
        self = super().__new__(cls)
        self._sessions = list(sessions) or ["t0.1"]
        self._started, self._killed, self._refusal = [], [], ""
        self._retryable = False
        self._kill_refusal = None
        self.running = True
        return self

    @property
    def started(self) -> list[str]:
        return self._started

    @property
    def killed(self) -> list[str]:
        return self._killed

    def refuse(self, reason: str, *, retryable: bool = False) -> None:
        self._refusal, self._retryable = reason, retryable

    def refuse_kill(self, reason: str, *, retryable: bool = False) -> None:
        self._kill_refusal = (
            RetryableRefusalError if retryable else SessionRefusedError
        )(reason)

    def allow_kill(self) -> None:
        self._kill_refusal = None

    def ask(self, request: ControlRequest) -> SuccessReply:
        if self._refusal:
            raise (RetryableRefusalError if self._retryable else SessionRefusedError)(
                self._refusal
            )
        if isinstance(request, NewRequest):
            self._started.append(self._sessions.pop(0))
            return SuccessReply(2, {"session": self._started[-1]})
        if isinstance(request, KillRequest):
            if self._kill_refusal is not None:
                raise self._kill_refusal
            self._killed.append(request.session)
            return SuccessReply(2, {})
        assert isinstance(request, ListRequest)
        state = "running" if self.running else "exited"
        held = [{"session": name, "state": state} for name in self._started]
        return SuccessReply(2, {"sessions": held})
