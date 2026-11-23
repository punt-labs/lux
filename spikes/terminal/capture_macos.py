# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Capture the running lux-display window to a PNG on macOS, via ffmpeg.

The terminal spike's external window capture (macOS). Kept here because the spike
scripts raise and locate the Display window by PID, which the in-process
`lux display screenshot` does not do. Same contract as the retired DES-091 tool:

- The window is resolved by PID: the on-screen, layer-0 window owned by a
  running ``luxd-display`` process. No title-only fallback, because this is
  a verification tool and capturing the wrong window would be false evidence.
- The output path never holds a stale image: it is removed first, the
  capture goes to a temp file, and only a verified capture is moved into place.
- A blank (uniform) capture is rejected by a pixel standard-deviation check.

Mechanism: ``ffmpeg -f avfoundation`` grabs one frame of the display the
window is on ("Capture screen N"), then the window's rectangle is cropped
out, scaled from points to pixels for that display. This captures what is
on screen, so the window must be visible: it is raised first (via System
Events), and the capture is rejected if another window covers part of it.

Prereqs: ffmpeg (``brew install ffmpeg``), the ``[display]`` extra (pyobjc
Quartz + AppKit, Pillow), and Screen Recording permission for the terminal
app (System Settings > Privacy & Security > Screen Recording).

Usage: capture_macos.py [output-path] [--interval SECONDS --count N]
Default output path: $SCREENSHOT_OUT, else .tmp/lux-screenshot.png.
With --count N it writes NAME-0001.png, NAME-0002.png, ...
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

BLACK_STDDEV_THRESHOLD = 1.0  # on 0-255 grey; a blank or locked capture is ~0
FFMPEG_TIMEOUT_S = 20
MIN_WINDOW_PT = 200  # ignore menu/status strips the process also owns
BOUNDS_TOLERANCE_PT = 1.0  # window drift allowed between query and grab
MAX_COVERED = 0.01  # share of the window other windows may cover
# Bundle IDs of the Dock and Notification Center, which keep a transparent,
# screen-sized window above every app window (seen on macOS 26.6). Matched by
# bundle ID because kCGWindowOwnerName is localized. Only a window of theirs
# exactly matching a screen is skipped. A notification banner draws inside
# Notification Center's full-screen window, so a banner over Lux is not detected.
SCREEN_OVERLAY_BUNDLES = frozenset({"com.apple.dock", "com.apple.notificationcenterui"})


class ScreenshotError(Exception):
    """Capture could not be produced or verified."""


def _quartz() -> Any:
    """pyobjc Quartz, imported lazily so a missing [display] extra fails cleanly."""
    try:
        import Quartz  # type: ignore[import-untyped]
    except ImportError as e:
        msg = f"cannot import Quartz ({e}) -- install the [display] extra"
        raise ScreenshotError(msg) from e
    return Quartz


def _appkit() -> Any:
    """pyobjc AppKit, imported lazily like `_quartz`."""
    try:
        import AppKit  # type: ignore[import-untyped]
    except ImportError as e:
        msg = f"cannot import AppKit ({e}) -- install the [display] extra"
        raise ScreenshotError(msg) from e
    return AppKit


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_cg(cls, b: Any) -> Rect:
        return cls(float(b["X"]), float(b["Y"]), float(b["Width"]), float(b["Height"]))

    def contains(self, o: Rect) -> bool:
        return (
            o.x >= self.x
            and o.y >= self.y
            and o.x + o.w <= self.x + self.w
            and o.y + o.h <= self.y + self.h
        )

    def overlap(self, o: Rect) -> float:
        dx = min(self.x + self.w, o.x + o.w) - max(self.x, o.x)
        dy = min(self.y + self.h, o.y + o.h) - max(self.y, o.y)
        return max(0.0, dx) * max(0.0, dy)


@dataclass(frozen=True)
class Window:
    number: int
    pid: int
    bounds: Rect  # global display coordinates, points, origin top-left


@dataclass(frozen=True)
class Screen:
    index: int  # avfoundation "Capture screen N" index
    bounds: Rect  # points


def display_pids() -> list[int]:
    out = subprocess.run(
        ["pgrep", "-x", "luxd-display"], capture_output=True, text=True, check=False
    ).stdout
    return [int(p) for p in out.split()]


def find_window(pids: list[int]) -> Window:
    q = _quartz()
    opts = q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements
    infos = q.CGWindowListCopyWindowInfo(opts, q.kCGNullWindowID) or []
    candidates: list[Window] = []
    for w in infos:
        pid = int(w.get("kCGWindowOwnerPID", -1))
        if pid not in pids or int(w.get("kCGWindowLayer", -1)) != 0:
            continue
        rect = Rect.from_cg(w["kCGWindowBounds"])
        if rect.w >= MIN_WINDOW_PT and rect.h >= MIN_WINDOW_PT:
            candidates.append(Window(int(w["kCGWindowNumber"]), pid, rect))
    if not candidates:
        msg = (
            f"luxd-display is running (pid(s): {pids}) but has no visible main "
            "window -- minimized, on another Space, or still starting?"
        )
        raise ScreenshotError(msg)
    return max(candidates, key=lambda c: c.bounds.w * c.bounds.h)


def screens() -> list[Screen]:
    """Displays in avfoundation order (CGGetActiveDisplayList order, main first)."""
    q = _quartz()
    err, ids, n = q.CGGetActiveDisplayList(16, None, None)
    if err:
        msg = f"CGGetActiveDisplayList failed ({err})"
        raise ScreenshotError(msg)
    out = []
    for i, d in enumerate(ids[:n]):
        b = q.CGDisplayBounds(d)
        rect = Rect(b.origin.x, b.origin.y, b.size.width, b.size.height)
        out.append(Screen(i, rect))
    return out


def screen_for(win: Window, all_screens: list[Screen]) -> Screen:
    best = max(all_screens, key=lambda s: s.bounds.overlap(win.bounds))
    if not best.bounds.contains(win.bounds):
        msg = (
            "the Lux window spans more than one display or is partly off-screen; "
            "move it fully onto one display"
        )
        raise ScreenshotError(msg)
    return best


def raise_window(pid: int) -> None:
    """Bring the Lux window to the front.

    NSRunningApplication.activateWithOptions_ alone does not raise a
    background process's window on recent macOS (activation is cooperative),
    so ask System Events first; it needs Accessibility/Automation permission
    for the terminal, and the AppKit call stays as a fallback.
    """
    script = (
        'tell application "System Events" to set frontmost of '
        f"(first process whose unix id is {pid}) to true"
    )
    r = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    if r.returncode != 0:
        ak = _appkit()
        app = ak.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            app.activateWithOptions_(ak.NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.5)  # let the window server bring it forward


def union_area(rects: list[Rect]) -> float:
    """Area covered by at least one rect (coordinate compression, exact)."""
    xs = sorted({v for r in rects for v in (r.x, r.x + r.w)})
    area = 0.0
    for x0, x1 in pairwise(xs):
        spans = sorted((r.y, r.y + r.h) for r in rects if r.x <= x0 and r.x + r.w >= x1)
        top = float("-inf")
        for y0, y1 in spans:
            y0 = max(y0, top)
            if y1 > y0:
                area += (x1 - x0) * (y1 - y0)
                top = y1
    return area


def bundle_id(pid: int) -> str:
    """Bundle ID of the running app with this PID, or "" when it has none."""
    app = _appkit().NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    return str(app.bundleIdentifier() or "") if app is not None else ""


def is_screen_overlay(info: Any, all_screens: list[Screen]) -> bool:
    """True for a known system overlay window that spans a whole screen."""
    r = Rect.from_cg(info["kCGWindowBounds"])
    if not any(r == s.bounds for s in all_screens):
        return False
    return bundle_id(int(info.get("kCGWindowOwnerPID", -1))) in SCREEN_OVERLAY_BUNDLES


def occluded_fraction(win: Window, all_screens: list[Screen]) -> float:
    """Share of the window covered by on-screen windows stacked above it.

    Any layer counts, but only where it overlaps the window's own bounds, so
    floating panels are caught while menu-bar and dock chrome elsewhere on the
    screen is not. Overlapping coverers are measured once, as a union.
    Screen-sized system overlays (`is_screen_overlay`) are skipped.
    """
    q = _quartz()
    above = (
        q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionOnScreenAboveWindow, win.number
        )
        or []
    )
    b = win.bounds
    clipped: list[Rect] = []
    for w in above:
        if float(w.get("kCGWindowAlpha", 1)) == 0 or is_screen_overlay(w, all_screens):
            continue
        r = Rect.from_cg(w["kCGWindowBounds"])
        x0, y0 = max(b.x, r.x), max(b.y, r.y)
        x1, y1 = min(b.x + b.w, r.x + r.w), min(b.y + b.h, r.y + r.h)
        if x1 > x0 and y1 > y0:
            clipped.append(Rect(x0, y0, x1 - x0, y1 - y0))
    return min(1.0, union_area(clipped) / (b.w * b.h))


def grab_screen(index: int, dest: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        msg = "ffmpeg not found (brew install ffmpeg)"
        raise ScreenshotError(msg)
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "avfoundation", "-pixel_format", "bgr0", "-framerate", "30",
        "-capture_cursor", "0", "-i", f"Capture screen {index}:none",
        "-frames:v", "1", "-update", "1", "-y", str(dest),
    ]  # fmt: skip
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as e:
        msg = "ffmpeg timed out grabbing the screen"
        raise ScreenshotError(msg) from e
    if not dest.exists() or dest.stat().st_size == 0:
        lines = [ln for ln in r.stderr.splitlines() if "NSKVONotifying" not in ln]
        detail = "\n".join(lines).strip() or f"exit {r.returncode}"
        msg = f"ffmpeg produced no image: {detail}"
        raise ScreenshotError(msg)


def check_window_unmoved(before: Window, after: Window) -> None:
    """Fail if the window moved or resized between the bounds query and the grab."""
    a, b = before.bounds, after.bounds
    drift = max(abs(a.x - b.x), abs(a.y - b.y), abs(a.w - b.w), abs(a.h - b.h))
    # Quartz reports whole points; one point absorbs rounding, not a real move.
    if before.number != after.number or drift > BOUNDS_TOLERANCE_PT:
        msg = f"the Lux window moved or resized during capture ({a} -> {b})"
        raise ScreenshotError(msg)


def crop_and_verify(full: Path, win: Window, scr: Screen, dest: Path) -> None:
    from PIL import Image, ImageStat

    try:
        with Image.open(full) as im:
            s = im.width / scr.bounds.w  # pixels per point, from the capture itself
            left = (win.bounds.x - scr.bounds.x) * s
            top = (win.bounds.y - scr.bounds.y) * s
            box = (
                round(left),
                round(top),
                round(left + win.bounds.w * s),
                round(top + win.bounds.h * s),
            )
            # PIL pads an out-of-frame crop with black, which the stddev gate
            # below would not catch when the rest of the frame has content.
            if box[0] < 0 or box[1] < 0 or box[2] > im.width or box[3] > im.height:
                msg = (
                    f"window box {box} is outside the {im.width}x{im.height} "
                    "capture -- the window moved or changed display during capture"
                )
                raise ScreenshotError(msg)
            shot = im.crop(box).convert("RGB")
    except (OSError, ValueError) as e:  # UnidentifiedImageError is an OSError
        msg = f"ffmpeg output is not a readable image: {e}"
        raise ScreenshotError(msg) from e
    stddev = ImageStat.Stat(shot.convert("L")).stddev[0]
    if stddev < BLACK_STDDEV_THRESHOLD:
        msg = (
            f"capture is blank (stddev={stddev:.2f}) -- screen locked, or Screen "
            "Recording permission missing for this terminal app?"
        )
        raise ScreenshotError(msg)
    # The capture is a picture of the user's screen: owner-only, never followed
    # through a planted symlink, never over an existing file.
    try:
        dest.unlink(missing_ok=True)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            shot.save(f, format="PNG")
    except OSError as e:  # disk full, EPERM, ...: main() only catches ScreenshotError
        msg = f"could not write capture to {dest}: {e}"
        raise ScreenshotError(msg) from e


def check_not_occluded(win: Window, all_screens: list[Screen]) -> None:
    """Fail if other windows cover more than MAX_COVERED of the window."""
    if (cov := occluded_fraction(win, all_screens)) > MAX_COVERED:
        msg = f"the Lux window is {cov:.0%} covered by other windows"
        raise ScreenshotError(msg)


def scratch_dir() -> tempfile.TemporaryDirectory[str]:
    try:
        return tempfile.TemporaryDirectory()
    except OSError as e:
        msg = f"could not create a temporary directory: {e}"
        raise ScreenshotError(msg) from e


def capture(out: Path, *, raise_first: bool = True) -> Path:
    """One verified capture of the Lux window to `out`. Raises ScreenshotError."""
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        # Resolve the directory only: a symlink at the final component must stay
        # a link, so the unlink and replace below act on it, never its target.
        out = out.parent.resolve() / out.name
    except OSError as e:
        msg = f"could not prepare the output directory for {out}: {e}"
        raise ScreenshotError(msg) from e
    if sys.platform != "darwin":
        msg = "capture_macos.py is macOS-only"
        raise ScreenshotError(msg)
    # Past the platform guard we are committed to this path: every later exit
    # (permission, no window, occlusion) must leave no stale image to read.
    out.unlink(missing_ok=True)
    q = _quartz()
    if not q.CGPreflightScreenCaptureAccess():
        q.CGRequestScreenCaptureAccess()
        msg = (
            "no Screen Recording permission for this terminal app -- grant it "
            "in System Settings > Privacy & Security > Screen Recording, then "
            "restart the terminal"
        )
        raise ScreenshotError(msg)
    pids = display_pids()
    if not pids:
        msg = "luxd-display is not running -- start it first (lux display start)"
        raise ScreenshotError(msg)
    win = find_window(pids)
    if raise_first:
        raise_window(win.pid)
        win = find_window(pids)  # bounds can change when activated
    all_screens = screens()
    check_not_occluded(win, all_screens)
    scr = screen_for(win, all_screens)
    tmp = out.with_name(f".{out.stem}.tmp{out.suffix or '.png'}")
    with scratch_dir() as td:
        full = Path(td) / "screen.png"
        grab_screen(scr.index, full)
        post = find_window(pids)
        check_window_unmoved(win, post)
        # Residual limit: these two stack checks narrow, but cannot eliminate, a
        # cover that was present only in the single frame ffmpeg grabbed and
        # left before this query. Closing it needs frame-tied capture (the
        # in-process path of DES-028), which this tool does not have.
        # A window raised over ours mid-grab is in the frame, so re-check with
        # the post-grab window, the one the frame actually reflects.
        check_not_occluded(post, all_screens)
        try:
            crop_and_verify(full, win, scr, tmp)
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
    return out


def clear_stale_series(out: Path, count: int) -> None:
    """Remove NAME-NNNN images above `count` left by an earlier, longer series."""
    suffix = out.suffix or ".png"
    pattern = re.compile(rf"{re.escape(out.stem)}-(\d{{4}}){re.escape(suffix)}")
    try:
        for p in out.parent.glob(f"{out.stem}-*{suffix}"):
            m = pattern.fullmatch(p.name)
            if m and int(m[1]) > count:
                p.unlink()
    except OSError as e:
        msg = f"could not clear stale series images beside {out}: {e}"
        raise ScreenshotError(msg) from e


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture the Lux window (macOS).")
    ap.add_argument("out", nargs="?", default=os.environ.get("SCREENSHOT_OUT"))
    ap.add_argument("--out", dest="out_flag")
    ap.add_argument("--interval", type=float, default=0.0, help="seconds apart")
    ap.add_argument("--count", type=int, default=1, help="number of captures")
    ap.add_argument("--no-raise", action="store_true", help="keep window order")
    a = ap.parse_args()
    if a.count < 1:
        ap.error(f"--count must be at least 1, got {a.count}")
    out = Path(a.out_flag or a.out or ".tmp/lux-screenshot.png")
    try:
        if a.count <= 1:
            print(capture(out, raise_first=not a.no_raise))
            return 0
        clear_stale_series(out, a.count)
        for i in range(1, a.count + 1):
            t0 = time.monotonic()
            path = out.with_name(f"{out.stem}-{i:04d}{out.suffix or '.png'}")
            first = i == 1 and not a.no_raise
            print(capture(path, raise_first=first), flush=True)
            if i < a.count:
                time.sleep(max(0.0, a.interval - (time.monotonic() - t0)))
    except ScreenshotError as e:
        print(f"capture_macos.py: error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
