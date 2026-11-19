"""Retire a failed session's child without blocking the daemon pump."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.ptyd.process_retirement import ProcessRetirement
from punt_lux.ptyd.session_state import SessionState

if TYPE_CHECKING:
    from types import TracebackType

    from punt_lux.ptyd.process_port import ProcessPort

logger = logging.getLogger(__name__)


class SessionLifecycle:
    """Own terminal operation failure and the resulting process retirement."""

    _name: str
    _process: ProcessPort
    _pending: ProcessRetirement
    _state: SessionState

    def __new__(cls, name: str, process: ProcessPort) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._process = process
        self._pending = ProcessRetirement()
        self._state = SessionState.RUNNING
        return self

    @property
    def state(self) -> SessionState:
        return self._state

    @state.setter
    def state(self, value: SessionState) -> None:
        self._state = value

    def __enter__(self) -> None:
        pass

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self._state = SessionState.FAILED
            self._pending.add(self._name, self._process)
            self.pump()

    def pump(self) -> None:
        try:
            self._pending.pump()
        except RuntimeError:
            logger.exception("Terminal cleanup still pending for %s", self._name)
