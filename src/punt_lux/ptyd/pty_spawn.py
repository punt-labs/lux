"""forkpty creates the terminal child's session, process group and controlling PTY."""

from __future__ import annotations

import contextlib
import os
import pty
from collections.abc import Sequence
from typing import Never

from punt_lux.ptyd.environment import user_environment
from punt_lux.ptyd.terminal_child import TerminalChild


class PtySpawn:
    @staticmethod
    def start(argv: Sequence[str] | None) -> tuple[TerminalChild, int]:
        env = user_environment()
        command = list(argv) if argv else [env["SHELL"], "-l"]
        pid, fd = pty.fork()
        if pid == 0:
            PtySpawn._exec(command, env)
        return TerminalChild(pid), fd

    @staticmethod
    def _exec(argv: list[str], env: dict[str, str]) -> Never:
        try:
            os.execvpe(argv[0], argv, env)  # noqa: S606 -- explicitly requested argv
        except (OSError, ValueError, TypeError) as error:
            with contextlib.suppress(OSError):
                os.write(2, f"exec failed: {error}\n".encode("utf-8", "replace"))
        finally:
            os._exit(127)
