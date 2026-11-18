"""Version-one frame vocabulary shared by codecs and channel dispatch."""

from __future__ import annotations

from enum import IntEnum


class FrameError(ValueError):
    """Malformed framing, a size-limit violation, or use after a fatal error."""


class FrameKind(IntEnum):
    """Channel zero carries JSON control messages as DATA frames."""

    DATA = 0
    SNAPSHOT = 1
    CREDIT = 2
    RESIZE = 3
    CLOSE = 4
