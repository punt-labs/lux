"""Set the running process's ``ps``/``top``/Activity Monitor name."""

from __future__ import annotations


def set_process_title(name: str) -> None:
    """Set this process's title. No-op if ``setproctitle`` is not installed."""
    try:
        import setproctitle
    except ImportError:
        return
    setproctitle.setproctitle(name)
