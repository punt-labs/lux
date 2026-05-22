"""macOS-specific display tweaks for the Lux ImGui window.

Without a ``.app`` bundle the process advertises itself as ``python3.14``
in the Dock and Cmd-Tab. We can't easily fix the bundle identity at
runtime, so we hide the entry instead via the Accessory activation
policy — the window stays visible, the Dock tile and app-switcher
entry go away.
"""

from __future__ import annotations

import logging
import platform
from typing import Any

logger = logging.getLogger(__name__)


def hide_from_dock_and_cmd_tab() -> None:
    """Apply ``NSApplicationActivationPolicyAccessory`` on macOS.

    Must be called after NSApplication has been initialized (e.g. from
    the ImGui ``post_init`` callback). No-op on non-Darwin platforms.
    Failure is logged at warning level so the regression is visible —
    silent failure here means the user sees "python3.14" in the Dock
    with no signal.
    """
    if platform.system() != "Darwin":
        return
    try:
        import AppKit as _AppKit  # type: ignore[import-untyped,import-not-found] # pyright: ignore[reportMissingImports]

        _ak: Any = _AppKit  # PY-TS-9: AppKit is an untyped pyobjc shim.
        _ak.NSApplication.sharedApplication().setActivationPolicy_(
            _ak.NSApplicationActivationPolicyAccessory
        )
    except (ImportError, AttributeError, RuntimeError) as exc:
        logger.warning(
            "macOS Accessory activation policy not applied (%s); "
            "the display may show as 'python3.14' in the Dock",
            exc,
        )
