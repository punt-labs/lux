"""Restart the optional machine-local terminal daemon for `make restart`."""

from __future__ import annotations

import sys

from punt_lux.logging_config import configure_logging
from punt_lux.ptyd.service import TerminalService
from punt_lux.service import ServiceActionFailedError, ServiceNotInstalledError


def main() -> int:
    """Restart the running PTY service without starting it on inactive machines."""
    configure_logging("lux", "cli")
    service = TerminalService()
    if not service.is_active:
        print("luxd-pty is not running; skipping restart.")
        return 0
    print("Restarting luxd-pty ends its terminal sessions.", flush=True)
    try:
        print(service.restart())
    except ServiceNotInstalledError:
        print("luxd-pty is not installed; skipping restart.")
    except ServiceActionFailedError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
