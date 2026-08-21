"""macOS-specific NSApplication activation policy for the Lux display.

The display sets ``NSApplicationActivationPolicyRegular`` so the OS gives it
a Dock icon and lists it in Cmd-Tab — standard macOS app behaviour when a
window is on screen and there is no menubar/status-item entry.

When the menubar-app epic (lux-mxvy.3) ships, this flips to
``NSApplicationActivationPolicyAccessory`` so the menubar controls visibility
and the Dock stays clean.
"""

from __future__ import annotations

import logging
import platform
from typing import Any

logger = logging.getLogger(__name__)


def set_regular_activation_policy() -> None:
    """Apply ``NSApplicationActivationPolicyRegular`` on macOS.

    Must be called after NSApplication has been initialized (from the ImGui
    ``post_init`` callback). No-op on non-Darwin platforms. Failure is logged
    at warning level — silent failure would leave the window with no Dock
    icon on macOS with no signal to anyone.
    """
    if platform.system() != "Darwin":
        return
    try:
        import AppKit as _AppKit  # type: ignore[import-untyped,import-not-found] # pyright: ignore[reportMissingImports]

        _ak: Any = _AppKit  # PY-TS-9: AppKit is an untyped pyobjc shim.
        _ak.NSApplication.sharedApplication().setActivationPolicy_(
            _ak.NSApplicationActivationPolicyRegular
        )
    except (ImportError, AttributeError, RuntimeError) as exc:
        logger.warning(
            "macOS Regular activation policy not applied (%s); "
            "the display window may lack a Dock icon",
            exc,
        )
