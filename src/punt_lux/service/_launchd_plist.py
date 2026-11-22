"""Installed launchd configuration and the job identity derived from it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self

from punt_lux.service._atomic_write import write_config_atomic
from punt_lux.service._launchctl import launchctl

if TYPE_CHECKING:
    from punt_lux.service import ServiceSpec


class LaunchdPlist:
    _spec: ServiceSpec
    _path: Path
    __slots__ = ("_path", "_spec")

    def __new__(cls, spec: ServiceSpec) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._path = (
            Path.home() / "Library" / "LaunchAgents" / f"{spec.launchd_label}.plist"
        )
        return self

    @property
    def spec(self) -> ServiceSpec:
        return self._spec

    @property
    def path(self) -> Path:
        return self._path

    @property
    def target(self) -> str:
        return f"{launchctl.gui_domain()}/{self._spec.launchd_label}"

    def installed_content(self) -> str:
        try:
            return self._path.read_text()
        except FileNotFoundError:
            return ""

    def write(self, content: str) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_config_atomic.write(self._path, content)
