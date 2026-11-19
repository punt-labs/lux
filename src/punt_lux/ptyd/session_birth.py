"""Transfer process ownership only after its authoritative parser is constructed."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.ptyd.session import TerminalSession

if TYPE_CHECKING:
    from punt_lux.protocol.pty.attach import AttachRequest
    from punt_lux.ptyd.process_factory import ProcessCreator
    from punt_lux.ptyd.process_retirement import ProcessRetirement


class SessionBirth:
    _factory: ProcessCreator
    _pending: ProcessRetirement

    def __new__(cls, factory: ProcessCreator, pending: ProcessRetirement) -> Self:
        self = super().__new__(cls)
        self._factory, self._pending = factory, pending
        return self

    def start(self, request: AttachRequest) -> TerminalSession:
        process = self._factory(request)
        self._pending.add(request.session, process)
        try:
            session = TerminalSession(request, process)
        except BaseException as error:
            try:
                self._pending.stop(request.session)
            except (OSError, RuntimeError) as cleanup:
                raise BaseExceptionGroup(
                    "session creation and cleanup failed", [error, cleanup]
                ) from error
            raise
        self._pending.forget(request.session)
        return session
