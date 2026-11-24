"""Lux daemon specifications and product-owned migration policy."""

from __future__ import annotations

from typing import ClassVar, Self, final

import punt_service
from punt_lux.service._binary_sweep_disk import DiskBinaryLegacySweep
from punt_lux.service.service_spec import DISPLAY_SPEC, HUB_SPEC

__all__ = ["DISPLAY_SPEC", "HUB_SPEC", "DisplayServiceManager", "HubServiceManager"]


@final
class HubServiceManager(punt_service.ServiceManager):
    """Supervise the Lux Hub with Lux's legacy uv-tool ownership policy."""

    __slots__ = ()
    _SPEC: ClassVar[punt_service.ServiceSpec] = HUB_SPEC

    def __new__(cls) -> Self:
        return super().__new__(cls, binary_sweep=DiskBinaryLegacySweep(cls._SPEC))


@final
class DisplayServiceManager(punt_service.ServiceManager):
    """Supervise the Lux Display with Lux's legacy uv-tool ownership policy."""

    __slots__ = ()
    _SPEC: ClassVar[punt_service.ServiceSpec] = DISPLAY_SPEC

    def __new__(cls) -> Self:
        return super().__new__(cls, binary_sweep=DiskBinaryLegacySweep(cls._SPEC))
