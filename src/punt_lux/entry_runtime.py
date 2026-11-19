"""Compose process diagnostics with Lux daemon and worker lifecycles."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Self, final

from punt_lux.logging_config import process_diagnostics
from punt_lux.proctitle import set_process_title
from punt_lux.usage import capture_usage

if TYPE_CHECKING:
    from collections.abc import Generator


@final
class DaemonRuntime:
    """Own the diagnostics and usage lifecycles of a named daemon."""

    _title: str
    __slots__ = ("_title",)

    def __new__(cls, process_title: str) -> Self:
        self = super().__new__(cls)
        self._title = process_title
        return self

    @contextmanager
    def run(self) -> Generator[None]:
        """Enter the daemon's runtime and set its process title."""
        with process_diagnostics("daemon", self._title), capture_usage():
            set_process_title(self._title)
            yield
