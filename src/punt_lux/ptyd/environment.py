"""Login identity for terminal children, independent of the Display process."""

from __future__ import annotations

import os
import pwd


class UserEnvironment:
    """Use the account's HOME/shell, excluding Display-only runtime variables."""

    @staticmethod
    def build() -> dict[str, str]:
        entry = pwd.getpwuid(os.getuid())
        excluded = {"LUX_SOCKET", "TERM_PROGRAM", "TERM_PROGRAM_VERSION"}
        env = {key: value for key, value in os.environ.items() if key not in excluded}
        env.update(
            HOME=entry.pw_dir,
            USER=entry.pw_name,
            LOGNAME=entry.pw_name,
            SHELL=entry.pw_shell or "/bin/sh",
            TERM="xterm-256color",
            COLORTERM="truecolor",
        )
        return env


user_environment = UserEnvironment.build
