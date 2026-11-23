"""Daemon composition: local owner plus optional long-lived Terminal launcher."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from punt_lux.pty.menu_process import MenuProcess
from punt_lux.pty.server import PtyServer


class PtyApplication:
    _server: PtyServer
    _menu: MenuProcess | None

    def __new__(cls, path: Path, *, menu: bool = True) -> Self:
        self = super().__new__(cls)
        self._server = PtyServer(path, idle_timeout=None if menu else 30)
        try:
            self._menu = MenuProcess() if menu else None
        except BaseException:
            self._server.close()
            raise
        return self

    def stop(self) -> None:
        self._server.stop()
        if self._menu is not None:
            self._menu.request_stop()

    def run(self) -> None:
        try:
            if self._menu is not None:
                self._menu.start()
            while self._server.tick():
                if self._menu is not None:
                    self._menu.poll()
        finally:
            try:
                if self._menu is not None:
                    self._menu.close()
            finally:
                self._server.close()
