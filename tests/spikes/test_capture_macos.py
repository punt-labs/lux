"""Evidence-integrity tests for spikes/terminal/capture_macos.py (no display needed).

The terminal spike's external window capture: the spike scripts locate and raise
the Display window by PID, which the in-process ``lux display screenshot`` does
not do, so the helper and these tests live on with the spike.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "spikes"
    / "terminal"
    / "capture_macos.py"
)
_spec = importlib.util.spec_from_file_location("capture_macos", _SCRIPT)
assert _spec is not None and _spec.loader is not None
sm: Any = importlib.util.module_from_spec(_spec)
sys.modules["capture_macos"] = sm
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


def test_window_occluded_after_grab_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    win = _window(20, 20, 100, 100)
    covered = iter([0.0, 0.5])  # clear at the first check, covered after the grab
    seen: list[Any] = []

    def occluded(w: Any, _screens: list[Any]) -> float:
        seen.append(w)
        return next(covered)

    def find(_pids: list[int]) -> Any:
        return win

    def grab(_index: int, dest: Path) -> None:
        dest.write_bytes(b"x")

    def crop(*_args: Any) -> None:
        raise AssertionError("an occluded capture must never reach the crop step")

    monkeypatch.setattr(sm.sys, "platform", "darwin")
    monkeypatch.setattr(
        sm,
        "_quartz",
        lambda: SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: True),
    )
    monkeypatch.setattr(sm, "display_pids", lambda: [1])
    monkeypatch.setattr(sm, "find_window", find)
    monkeypatch.setattr(sm, "occluded_fraction", occluded)
    monkeypatch.setattr(sm, "screens", lambda: [_screen()])
    monkeypatch.setattr(sm, "grab_screen", grab)
    monkeypatch.setattr(sm, "crop_and_verify", crop)
    out = tmp_path / "shot.png"
    with pytest.raises(sm.ScreenshotError, match="covered"):
        sm.capture(out, raise_first=False)
    assert not out.exists()
    assert len(seen) == 2


def test_unwritable_destination_raises_screenshot_error(tmp_path: Path) -> None:
    full = tmp_path / "full.png"
    _textured_frame(full, 400, 300)
    dest = tmp_path / "missing-dir" / "out.png"  # parent absent: open fails
    with pytest.raises(sm.ScreenshotError, match="could not write"):
        sm.crop_and_verify(full, _window(20, 20, 100, 100), _screen(), dest)


_DOCK = "com.apple.dock"
_NOTIFICATION_CENTER = "com.apple.notificationcenterui"
_PIDS = {"com.example.app": 100, _DOCK: 101, _NOTIFICATION_CENTER: 102}


def _cg(
    x: float,
    y: float,
    w: float,
    h: float,
    layer: int = 0,
    owner: str = "App",
    bundle: str = "com.example.app",
) -> dict[str, Any]:
    return {
        "kCGWindowOwnerName": owner,
        "kCGWindowOwnerPID": _PIDS[bundle],
        "kCGWindowLayer": layer,
        "kCGWindowAlpha": 1.0,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h},
    }


def _stack_above(monkeypatch: pytest.MonkeyPatch, above: list[dict[str, Any]]) -> None:
    def copy_info(_opts: int, _number: int) -> list[dict[str, Any]]:
        return above

    quartz = SimpleNamespace(
        kCGWindowListOptionOnScreenAboveWindow=1, CGWindowListCopyWindowInfo=copy_info
    )
    bundles = {pid: bundle for bundle, pid in _PIDS.items()}
    monkeypatch.setattr(sm, "_quartz", lambda: quartz)

    def bundle_id(pid: int) -> str:
        return bundles.get(pid, "")

    monkeypatch.setattr(sm, "bundle_id", bundle_id)


def test_floating_window_overlapping_lux_counts_as_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stack_above(monkeypatch, [_cg(0, 0, 100, 100, layer=25)])
    assert sm.occluded_fraction(_window(0, 0, 400, 400), []) > sm.MAX_COVERED


def test_system_chrome_not_overlapping_lux_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menu_bar = _cg(0, -30, 1000, 30, layer=24)
    _stack_above(monkeypatch, [menu_bar])
    assert sm.occluded_fraction(_window(0, 0, 400, 400), []) == 0.0


def test_overlapping_coverers_are_measured_as_a_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Each cover is 0.6% of the 400x400 window; stacked on one another they
    # still cover 0.6%, within MAX_COVERED, not 1.2%.
    _stack_above(monkeypatch, [_cg(0, 0, 40, 24), _cg(0, 0, 40, 24)])
    assert sm.occluded_fraction(_window(0, 0, 400, 400), []) == pytest.approx(0.006)


def _full_screen() -> Any:
    return sm.Screen(index=0, bounds=sm.Rect(0, 0, 1600, 1200))


@pytest.mark.parametrize("bundle", sorted(sm.SCREEN_OVERLAY_BUNDLES))
def test_screen_sized_system_overlay_is_ignored(
    monkeypatch: pytest.MonkeyPatch, bundle: str
) -> None:
    _stack_above(monkeypatch, [_cg(0, 0, 1600, 1200, layer=20, bundle=bundle)])
    win = _window(14, 44, 1200, 828)
    assert sm.occluded_fraction(win, [_full_screen()]) == 0.0


def test_screen_sized_window_of_another_owner_counts_as_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stack_above(monkeypatch, [_cg(0, 0, 1600, 1200, layer=20, owner="Overlay")])
    win = _window(14, 44, 1200, 828)
    assert sm.occluded_fraction(win, [_full_screen()]) == 1.0


def test_localized_system_overlay_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlay = _cg(
        0,
        0,
        1600,
        1200,
        layer=21,
        owner="Mitteilungszentrale",
        bundle=_NOTIFICATION_CENTER,
    )
    _stack_above(monkeypatch, [overlay])
    win = _window(14, 44, 1200, 828)
    assert sm.occluded_fraction(win, [_full_screen()]) == 0.0


def test_window_named_like_a_system_overlay_counts_as_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stack_above(monkeypatch, [_cg(0, 0, 1600, 1200, layer=20, owner="Dock")])
    win = _window(14, 44, 1200, 828)
    assert sm.occluded_fraction(win, [_full_screen()]) == 1.0


@pytest.mark.parametrize(
    ("app", "expected"),
    [
        (None, ""),
        (SimpleNamespace(bundleIdentifier=lambda: None), ""),
        (SimpleNamespace(bundleIdentifier=lambda: _DOCK), _DOCK),
    ],
)
def test_bundle_id_of_a_pid(
    monkeypatch: pytest.MonkeyPatch, app: Any, expected: str
) -> None:
    def running_app(_pid: int) -> Any:
        return app

    running = SimpleNamespace(runningApplicationWithProcessIdentifier_=running_app)
    appkit = SimpleNamespace(NSRunningApplication=running)
    monkeypatch.setattr(sm, "_appkit", lambda: appkit)
    assert sm.bundle_id(7) == expected


def test_system_owner_window_smaller_than_the_screen_counts_as_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = _cg(0, 0, 400, 400, layer=21, bundle=_NOTIFICATION_CENTER)
    _stack_above(monkeypatch, [panel])
    win = _window(0, 0, 400, 400)
    assert sm.occluded_fraction(win, [_full_screen()]) == 1.0


def test_system_overlay_sized_to_another_screen_counts_as_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stack_above(monkeypatch, [_cg(0, 0, 1600, 1200, layer=20, bundle=_DOCK)])
    win = _window(14, 44, 1200, 828)
    other = sm.Screen(index=1, bounds=sm.Rect(1600, 0, 1920, 1080))
    assert sm.occluded_fraction(win, [other]) == 1.0


def test_output_symlink_is_acted_on_not_its_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "decoy.txt"
    decoy.write_text("keep")
    link = tmp_path / "shot.png"
    link.symlink_to(decoy)
    quartz = SimpleNamespace(
        CGPreflightScreenCaptureAccess=lambda: False,
        CGRequestScreenCaptureAccess=lambda: None,
    )
    monkeypatch.setattr(sm.sys, "platform", "darwin")
    monkeypatch.setattr(sm, "_quartz", lambda: quartz)
    with pytest.raises(sm.ScreenshotError):
        sm.capture(link)
    assert decoy.read_text() == "keep"
    assert not link.is_symlink()


def test_unmakeable_output_dir_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, *_a: Any, **_k: Any) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(sm.Path, "mkdir", refuse)
    with pytest.raises(sm.ScreenshotError, match="output directory"):
        sm.capture(tmp_path / "sub" / "shot.png")


def test_missing_quartz_is_a_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "Quartz", None)
    with pytest.raises(sm.ScreenshotError, match="Quartz"):
        sm._quartz()


def test_temp_dir_failure_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise OSError("no space")

    monkeypatch.setattr(sm.tempfile, "TemporaryDirectory", refuse)
    with pytest.raises(sm.ScreenshotError, match="temporary"):
        sm.scratch_dir()


@pytest.mark.parametrize("count", ["0", "-1"])
def test_non_positive_count_is_rejected_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: str
) -> None:
    out = tmp_path / "shot.png"
    monkeypatch.setattr(sys, "argv", ["capture_macos.py", str(out), "--count", count])
    with pytest.raises(SystemExit) as exc:
        sm.main()
    assert exc.value.code != 0
    assert list(tmp_path.iterdir()) == []


def test_shorter_series_clears_stale_higher_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "shot.png"
    for n in range(3, 13):
        (tmp_path / f"shot-{n:04d}.png").write_bytes(b"old")
    keep = tmp_path / "other-0003.png"
    keep.write_bytes(b"unrelated")

    def fake_capture(path: Path, *, raise_first: bool = True) -> Path:
        path.write_bytes(b"new")
        return path

    monkeypatch.setattr(sm, "capture", fake_capture)
    monkeypatch.setattr(sys, "argv", ["capture_macos.py", str(out), "--count", "2"])
    assert sm.main() == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["other-0003.png", "shot-0001.png", "shot-0002.png"]
