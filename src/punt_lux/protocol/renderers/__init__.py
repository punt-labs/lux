"""Protocol-tier renderers — surface-independent, no display extras required.

These renderers live under ``protocol/`` (not ``display/``) because they have
zero ImGui dependency. They are usable on the Hub and in tests without the
``[display]`` optional extra installed.

- ``null``: do-nothing renderer for tiers that never paint (Hub, Agent).
- ``recording``: JSONL-appending renderer used by headless render assertions.
"""

from __future__ import annotations

from punt_lux.protocol.renderers.null import NullRenderer, NullRendererFactory
from punt_lux.protocol.renderers.recording import (
    RecordingLog,
    RecordingRenderer,
    RecordingRendererFactory,
)

__all__ = [
    "NullRenderer",
    "NullRendererFactory",
    "RecordingLog",
    "RecordingRenderer",
    "RecordingRendererFactory",
]
