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
            PtySpawn._enter_home(env.get("HOME"))
            os.execvpe(argv[0], argv, env)  # noqa: S606 -- explicitly requested argv
        except (OSError, ValueError, TypeError) as error:
            PtySpawn._warn(f"exec failed: {error}")
        finally:
            os._exit(127)

    @staticmethod
    def _enter_home(home: str | None) -> None:
        """Start the shell in the user's home, not luxd-pty's cwd.

        launchd services start at /, so without this the shell opens there. A
        missing or unusable HOME is reported to the terminal and the shell
        starts in the inherited cwd rather than failing to launch at all.
        """
        if home is None:
            PtySpawn._warn("HOME not set; starting shell in inherited cwd")
            return
        try:
            os.chdir(home)
        except OSError as error:
            PtySpawn._warn(f"cd to HOME failed, starting in inherited cwd: {error}")

    @staticmethod
    def _warn(message: str) -> None:
        """Write a notice to the child's PTY slave (fd 2), the user's terminal."""
        with contextlib.suppress(OSError):
            os.write(2, f"{message}\n".encode("utf-8", "replace"))
