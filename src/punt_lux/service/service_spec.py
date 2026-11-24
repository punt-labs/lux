"""Lux daemon identities and supervisor policy."""

from __future__ import annotations

import punt_service
from punt_lux.kernel.hub_defaults import DEFAULT_HUB_PORT

__all__ = ["DISPLAY_SPEC", "HUB_SPEC"]


HUB_SPEC: punt_service.ServiceSpec = punt_service.ServiceSpec(
    display_name="luxd",
    launchd_label="com.punt-labs.luxd-hub",
    systemd_unit="luxd-hub",
    systemd_description="Lux session hub daemon",
    binary_name="luxd-hub",
    extra_args=("--port", str(DEFAULT_HUB_PORT)),
    cli_verb="hub",
    process_name="luxd-hub",
    legacy_launchd_labels=("com.punt-labs.lux",),
    legacy_systemd_units=("lux",),
    legacy_binary_names=("luxd",),
    health_port=DEFAULT_HUB_PORT,
    cli_name="lux",
    log_path="~/.punt-labs/lux/logs/lux.log",
)


DISPLAY_SPEC: punt_service.ServiceSpec = punt_service.ServiceSpec(
    display_name="luxd-display",
    launchd_label="com.punt-labs.luxd-display",
    systemd_unit="luxd-display",
    systemd_description="Lux display window server",
    binary_name="luxd-display",
    extra_args=(),
    cli_verb="display",
    process_name="luxd-display",
    restart_on_crash_only=True,
    cli_name="lux",
    log_path="~/.punt-labs/lux/logs/lux.log",
)
