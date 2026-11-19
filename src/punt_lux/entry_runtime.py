"""Compose process diagnostics with Lux daemon and worker lifecycles."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from punt_lux.logging_config import process_diagnostics
from punt_lux.proctitle import set_process_title
from punt_lux.usage import capture_usage

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def daemon_runtime(process_title: str) -> Generator[None]:
    """Enter a daemon's diagnostics and usage lifecycles."""
    with process_diagnostics("daemon", process_title), capture_usage():
        set_process_title(process_title)
        yield
