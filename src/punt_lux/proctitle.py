"""Set the running process's ``ps``/``top``/Activity Monitor name."""

from __future__ import annotations

from setproctitle import setproctitle


def set_process_title(name: str) -> None:
    """Set this process's title."""
    setproctitle(name)
