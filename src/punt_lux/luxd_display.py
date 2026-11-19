"""luxd-display — the Lux display window process entry point.

Boots the ImGui render loop that renders the Hub's replicated UI. This is
the top-level executable launchd/systemd invoke directly — ``binary_name``
on :data:`~punt_lux.service.DISPLAY_SPEC` resolves to it. ``lux display
serve`` (``punt_lux.cli.display``) delegates to :meth:`DisplayEntryPoint.serve`
below for interactive/manual use; the two entry points share one
implementation.

This module requires the ``[display]`` extra — installing ``luxd-display``
implies it. Callers that may run without the extra (the ``lux`` CLI) import
this module lazily and catch ``ModuleNotFoundError`` themselves.
"""

from __future__ import annotations

import argparse
import logging
from typing import final

from punt_lux.display import RenderLoop
from punt_lux.entry_runtime import DaemonRuntime

__all__ = ["DisplayEntryPoint"]

logger = logging.getLogger(__name__)


@final
class DisplayEntryPoint:
    """Namespace for the ``luxd-display`` executable's boot sequence."""

    __slots__ = ()

    @staticmethod
    def serve(socket: str | None, *, test_auto_click: bool = False) -> None:
        """Start the Lux display server (the ImGui render loop process). Blocks.

        ``socket`` is the display's own listen path; ``None`` resolves the
        session default via :class:`DisplayPaths`.
        """
        with DaemonRuntime("luxd-display").run():
            logger.info("Starting Display")
            RenderLoop(socket, test_auto_click=test_auto_click).run()
            logger.info("Display stopped")

    @staticmethod
    def main() -> None:
        """Boot luxd-display — the top-level executable launchd/systemd invoke."""
        parser = argparse.ArgumentParser(description="Lux display window server")
        parser.add_argument("--socket", "-s", default=None, help="Socket path")
        parser.add_argument(
            "--test-auto-click",
            action="store_true",
            help="Auto-fire click events for buttons (testing)",
        )
        args = parser.parse_args()
        DisplayEntryPoint.serve(args.socket, test_auto_click=args.test_auto_click)
