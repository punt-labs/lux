"""SIGTERM -> hello_imgui clean-exit bridge for the ImGui render loop."""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from imgui_bundle import hello_imgui

__all__ = ["ExitSignal"]


@final
class ExitSignal:
    """Arm SIGTERM to request a clean exit from the ImGui loop.

    Python signal handlers only run between Python bytecodes; while the main
    thread is inside ``immapp.run()``'s C++ event loop, a handler that raised
    ``SystemExit`` here would unwind only the Python frames it fires in and
    never reach that loop, so the process would limp on until the
    supervisor's SIGKILL grace window expired. Setting ``app_shall_exit``
    asks the loop itself to stop at its next iteration, so ``before_exit``
    runs and the socket and pid files are cleaned up promptly, the same as
    any other exit path.

    Construct only after ``runner_params`` exists -- a SIGTERM that lands
    before that has nothing to set ``app_shall_exit`` on.
    """

    __slots__ = ("_runner_params",)

    _runner_params: hello_imgui.RunnerParams

    def __new__(cls, runner_params: hello_imgui.RunnerParams) -> Self:
        self = super().__new__(cls)
        self._runner_params = runner_params
        signal.signal(signal.SIGTERM, self._handle)
        return self

    def _handle(self, _signum: int, _frame: object) -> None:
        """Request that the ImGui loop stop at its next iteration."""
        self._runner_params.app_shall_exit = True
