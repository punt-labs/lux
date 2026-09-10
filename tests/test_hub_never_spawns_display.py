"""Structural guard: the Hub never spawns or controls the display process.

Demand-driven presence (display-presence-demand-driven.md §4): the Hub only
dials, holds content, and retries. Service lifecycle -- installing, starting,
stopping the display's launchd/systemd unit -- is the display's own concern,
never the Hub's. This grep-provable test pins that boundary so a future
change can't quietly reintroduce a Hub-side spawn/control path.
"""

from __future__ import annotations

import re
from pathlib import Path

_HUB_DIR = Path(__file__).parent.parent / "src" / "punt_lux" / "domain" / "hub"
_FORBIDDEN = re.compile(
    r"\bServiceManager\b|\bDISPLAY_SPEC\b|\bDisplayServiceManager\b"
)


def test_no_hub_module_references_the_display_service_lifecycle() -> None:
    offenders = {
        str(path.relative_to(_HUB_DIR))
        for path in _HUB_DIR.rglob("*.py")
        if _FORBIDDEN.search(path.read_text())
    }
    assert offenders == set(), (
        f"domain/hub/ must never name the display's service lifecycle: {offenders}"
    )
