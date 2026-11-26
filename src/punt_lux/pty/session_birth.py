"""Transfer process ownership only after its authoritative parser is constructed."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.session import TerminalSession

if TYPE_CHECKING:
    from punt_lux.pty.process_factory import ProcessCreator
    from punt_lux.pty.process_retirement import ProcessRetirement
    from punt_lux.pty.session_spec import SessionSpec


class SessionBirth:
    _factory: ProcessCreator
    _pending: ProcessRetirement

    def __new__(cls, factory: ProcessCreator, pending: ProcessRetirement) -> Self:
        self = super().__new__(cls)
        self._factory, self._pending = factory, pending
        return self

    def start(self, spec: SessionSpec) -> TerminalSession:
        process = self._factory(spec.request)
        self._pending.add(spec.name, process)
        try:
            session = TerminalSession(spec, process)
        except BaseException as error:
            try:
                self._pending.stop(spec.name)
            except (OSError, RuntimeError) as cleanup:
                raise BaseExceptionGroup(
                    "session creation and cleanup failed", [error, cleanup]
                ) from error
            raise
        self._pending.forget(spec.name)
        return session
