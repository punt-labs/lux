"""Protocol-tier renderers — surface-independent, no display extras required.

These renderers live under ``protocol/`` (not ``display/``) because they have
zero ImGui dependency. They are usable on the Hub and in tests without the
``[display]`` optional extra installed.

- ``raising``: fail-loud sentinel factory for tiers that never paint (Hub,
  Agent) and for the direct-construction default of ABC elements. A
  misrouted ``elem.render()`` raises ``RuntimeError`` instead of returning
  silently.
- ``recording``: JSONL-appending renderer used by headless render assertions.
"""

from __future__ import annotations

from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.protocol.renderers.recording import (
    RecordingLog,
    RecordingRenderer,
    RecordingRendererFactory,
)

__all__ = [
    "RaisingRendererFactory",
    "RecordingLog",
    "RecordingRenderer",
    "RecordingRendererFactory",
]
