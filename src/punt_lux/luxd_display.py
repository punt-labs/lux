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
from pathlib import Path
from typing import final

from punt_lux.display import RenderLoop
from punt_lux.log_level import level_from_env
from punt_lux.paths import DisplayPaths

__all__ = ["DisplayEntryPoint"]


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
        dp = DisplayPaths(Path(socket) if socket else None)
        log_path = dp.log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            filename=str(log_path),
            level=level_from_env("INFO"),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        server = RenderLoop(socket, test_auto_click=test_auto_click)
        server.run()

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
