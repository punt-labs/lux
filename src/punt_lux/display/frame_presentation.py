"""Frame presentation hints, independent of render-loop lifecycle and IO."""

from __future__ import annotations

from typing import Any, ClassVar

from punt_lux.display.replica import Frame


class FramePresentation:
    """Translate a frame's declarative hints into native window arguments."""

    _FLAG_MAP: ClassVar[dict[str, str]] = {
        "no_resize": "no_resize",
        "no_collapse": "no_collapse",
        "auto_resize": "always_auto_resize",
        "no_title_bar": "no_title_bar",
        "no_background": "no_background",
        "no_scrollbar": "no_scrollbar",
    }

    @staticmethod
    def flags(frame: Frame, imgui: Any) -> int:
        """Map frame flag names to an ImGui window flags bitmask."""
        result = 0
        if not frame.hints.flags:
            return result
        for key, enabled in frame.hints.flags.items():
            if not enabled:
                continue
            attr = FramePresentation._FLAG_MAP.get(key)
            if attr is None:
                continue
            flag = getattr(imgui.WindowFlags_, attr, None)
            if flag is not None:
                result |= flag.value
        return result

    @staticmethod
    def initial_size(
        frame: Frame, default_size: tuple[float, float]
    ) -> tuple[float, float]:
        """Return the frame's own initial size, or ``default_size`` if unset."""
        if not frame.initial_size:
            return default_size
        return float(frame.initial_size[0]), float(frame.initial_size[1])
