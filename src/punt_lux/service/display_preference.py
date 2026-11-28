"""Resolve display preferences and migrate legacy checkout settings read-only."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from punt_lux.service.config import ConfigManager, LuxConfig
from punt_lux.service.repo_activation import PERSONAL, Checkout

DEFAULT_CONFIG_PATH = PERSONAL / "display.local.md"
LEGACY_CONFIG_PATH = Path(".punt-labs/lux.md")


class DisplayPreference:
    _checkout: Checkout | None
    _main: Checkout | None
    _directory: Path
    __slots__ = ("_checkout", "_directory", "_main")

    def __new__(cls, directory: Path) -> Self:
        self = super().__new__(cls)
        self._directory = directory.resolve()
        self._checkout = Checkout.find(self._directory)
        self._main = self._main_checkout()
        return self

    def _main_checkout(self) -> Checkout | None:
        if self._checkout is None:
            return None
        try:
            return Checkout.resolve(self._checkout.root, main=True)
        except ValueError:
            return self._checkout

    @property
    def _local(self) -> Path:
        return (
            self._main.root if self._main else self._directory
        ) / DEFAULT_CONFIG_PATH

    @property
    def _legacy(self) -> Path:
        root = self._checkout.root if self._checkout else self._directory
        main = self._main.root if self._main else root
        legacy = root / LEGACY_CONFIG_PATH
        return legacy if legacy.exists() else main / LEGACY_CONFIG_PATH

    def read(self) -> LuxConfig:
        local = self._local
        return ConfigManager(local if local.exists() else self._legacy).read()

    def write(self, field: str) -> None:
        local = self._local
        if self._main is not None:
            self._main.require_private(local)
        ConfigManager(local).write_field("display", field)

    def migrate(self) -> None:
        if not self._local.exists() and (legacy := self._legacy).is_file():
            self.write(ConfigManager(legacy).read().display)


def current_display() -> LuxConfig:
    """Read the display preference for the current working directory."""
    return DisplayPreference(Path.cwd()).read()
