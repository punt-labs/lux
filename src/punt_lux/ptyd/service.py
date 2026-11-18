"""Machine-local opt-in supervisor registration, independent of Display demand."""

from __future__ import annotations

from typing import ClassVar

from punt_lux.service import ServiceManager, ServiceSpec


class TerminalService(ServiceManager):
    __slots__ = ()
    _SPEC: ClassVar[ServiceSpec] = ServiceSpec(
        display_name="luxd-pty",
        launchd_label="com.punt-labs.luxd-pty",
        systemd_unit="luxd-pty",
        systemd_description="Lux terminal owner and menu launcher",
        binary_name="luxd-pty",
        extra_args=(),
        log_stem="luxd-pty",
        cli_verb="terminal",
        process_name="luxd-pty",
    )

    def enable(self) -> str:
        """Install and start only on the machine whose operator enables it."""
        installed = self.install()
        return installed if self.is_active else installed + "\n" + self.start()

    def disable(self) -> str:
        """Explicit disable stops held programs and removes supervisor registration."""
        return self.uninstall()
