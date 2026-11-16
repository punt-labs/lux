"""Evidence-integrity tests for scripts/screenshot_macos.py (no display needed)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "screenshot_macos.py"
_spec = importlib.util.spec_from_file_location("screenshot_macos", _SCRIPT)
assert _spec is not None and _spec.loader is not None
sm: Any = importlib.util.module_from_spec(_spec)
sys.modules["screenshot_macos"] = sm
_spec.loader.exec_module(sm)


def _textured_frame(path: Path, width: int, height: int) -> None:
    """Write a frame with plenty of variance so the stddev gate passes."""
    im = Image.new("RGB", (width, height))
    im.putdata(
        [
            ((x * 7) % 256, (y * 13) % 256, (x + y) % 256)
            for y in range(height)
            for x in range(width)
        ]
    )
    im.save(path)


def _window(x: float, y: float, w: float, h: float) -> Any:
    return sm.Window(number=1, pid=1, bounds=sm.Rect(x, y, w, h))


def _screen() -> Any:
    # 200x150 points; the 400x300 frame below is a 2x (retina) capture of it.
    return sm.Screen(index=0, bounds=sm.Rect(0, 0, 200, 150))


def test_crop_fully_inside_frame_is_saved(tmp_path: Path) -> None:
    full, dest = tmp_path / "full.png", tmp_path / "out.png"
    _textured_frame(full, 400, 300)
    sm.crop_and_verify(full, _window(20, 20, 100, 100), _screen(), dest)
    assert Image.open(dest).size == (200, 200)


def test_window_moved_during_capture_is_rejected() -> None:
    with pytest.raises(sm.ScreenshotError, match="moved"):
        sm.check_window_unmoved(_window(20, 20, 100, 100), _window(60, 20, 100, 100))


def test_window_within_tolerance_is_accepted() -> None:
    sm.check_window_unmoved(_window(20, 20, 100, 100), _window(20.5, 20, 100, 100))


def test_crop_partly_outside_frame_is_rejected(tmp_path: Path) -> None:
    # Window spills past the right/bottom edge: PIL would black-pad the strip
    # and the stddev gate (content elsewhere) would still pass.
    full, dest = tmp_path / "full.png", tmp_path / "out.png"
    _textured_frame(full, 400, 300)
    with pytest.raises(sm.ScreenshotError, match="outside"):
        sm.crop_and_verify(full, _window(150, 100, 100, 100), _screen(), dest)
    assert not dest.exists()


def test_saved_capture_is_owner_only(tmp_path: Path) -> None:
    full, dest = tmp_path / "full.png", tmp_path / "out.png"
    _textured_frame(full, 400, 300)
    sm.crop_and_verify(full, _window(20, 20, 100, 100), _screen(), dest)
    assert dest.stat().st_mode & 0o777 == 0o600


def test_save_does_not_follow_a_planted_symlink(tmp_path: Path) -> None:
    full, dest = tmp_path / "full.png", tmp_path / "out.png"
    target = tmp_path / "victim.txt"
    target.write_text("keep")
    dest.symlink_to(target)
    _textured_frame(full, 400, 300)
    sm.crop_and_verify(full, _window(20, 20, 100, 100), _screen(), dest)
    assert target.read_text() == "keep"


def test_corrupt_capture_raises_screenshot_error(tmp_path: Path) -> None:
    full, dest = tmp_path / "full.png", tmp_path / "out.png"
    full.write_bytes(b"\x89PNG\r\n\x1a\ntruncated")
    with pytest.raises(sm.ScreenshotError, match="readable image"):
        sm.crop_and_verify(full, _window(20, 20, 100, 100), _screen(), dest)


def test_guard_failure_keeps_prior_screenshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "shot.png"
    out.write_bytes(b"good earlier capture")
    monkeypatch.setattr(sm.sys, "platform", "linux")
    with pytest.raises(sm.ScreenshotError, match="macOS-only"):
        sm.capture(out)
    assert out.read_bytes() == b"good earlier capture"


def test_missing_permission_leaves_no_stale_screenshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quartz = SimpleNamespace(
        CGPreflightScreenCaptureAccess=lambda: False,
        CGRequestScreenCaptureAccess=lambda: None,
    )

    out = tmp_path / "shot.png"
    out.write_bytes(b"good earlier capture")
    monkeypatch.setattr(sm.sys, "platform", "darwin")
    monkeypatch.setattr(sm, "_quartz", lambda: quartz)
    with pytest.raises(sm.ScreenshotError, match="Screen Recording"):
        sm.capture(out)
    # A caller reading by path must never mistake an old capture for new evidence.
    assert not out.exists()
