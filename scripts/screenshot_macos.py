# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Capture the running lux-display window to a PNG on macOS, via ffmpeg.

macOS counterpart of scripts/screenshot.sh (Linux, DES-091). Same contract:

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

Usage: screenshot_macos.py [output-path] [--interval SECONDS --count N]
Default output path: $SCREENSHOT_OUT, else .tmp/lux-screenshot.png.
With --count N it writes NAME-0001.png, NAME-0002.png, ...
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BLACK_STDDEV_THRESHOLD = 1.0  # on 0-255 grey; a blank or locked capture is ~0
FFMPEG_TIMEOUT_S = 20
MIN_WINDOW_PT = 200  # ignore menu/status strips the process also owns
BOUNDS_TOLERANCE_PT = 1.0  # window drift allowed between query and grab
MAX_COVERED = 0.01  # share of the window other windows may cover


class ScreenshotError(Exception):
    """Capture could not be produced or verified."""


def _quartz() -> Any:
    """pyobjc Quartz, imported lazily so a missing [display] extra fails cleanly."""
    import Quartz  # type: ignore[import-untyped]

    return Quartz


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
        import AppKit as _AppKit  # type: ignore[import-untyped]

        ak: Any = _AppKit  # untyped pyobjc shim, as in punt_lux.display.macos
        app = ak.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            app.activateWithOptions_(ak.NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.5)  # let the window server bring it forward


def occluded_fraction(win: Window) -> float:
    """Share of the window covered by on-screen windows stacked above it."""
    q = _quartz()
    above = (
        q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionOnScreenAboveWindow, win.number
        )
        or []
    )
    covered = 0.0
    for w in above:
        if int(w.get("kCGWindowLayer", 0)) != 0:
            continue
        if float(w.get("kCGWindowAlpha", 1)) == 0:
            continue
        covered += win.bounds.overlap(Rect.from_cg(w["kCGWindowBounds"]))
    return min(1.0, covered / (win.bounds.w * win.bounds.h))


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
    dest.unlink(missing_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        shot.save(f, format="PNG")


def capture(out: Path, *, raise_first: bool = True) -> Path:
    """One verified capture of the Lux window to `out`. Raises ScreenshotError."""
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "darwin":
        msg = "screenshot_macos.py is macOS-only (use screenshot.sh on Linux)"
        raise ScreenshotError(msg)
    q = _quartz()
    if not q.CGPreflightScreenCaptureAccess():
        q.CGRequestScreenCaptureAccess()
        msg = (
            "no Screen Recording permission for this terminal app -- grant it "
            "in System Settings > Privacy & Security > Screen Recording, then "
            "restart the terminal"
        )
        raise ScreenshotError(msg)
    out.unlink(missing_ok=True)  # never leave a stale image at the evidence path
    pids = display_pids()
    if not pids:
        msg = "luxd-display is not running -- start it first (lux display start)"
        raise ScreenshotError(msg)
    win = find_window(pids)
    if raise_first:
        raise_window(win.pid)
        win = find_window(pids)  # bounds can change when activated
    if (cov := occluded_fraction(win)) > MAX_COVERED:
        msg = f"the Lux window is {cov:.0%} covered by other windows"
        raise ScreenshotError(msg)
    scr = screen_for(win, screens())
    tmp = out.with_name(f".{out.stem}.tmp{out.suffix or '.png'}")
    with tempfile.TemporaryDirectory() as td:
        full = Path(td) / "screen.png"
        grab_screen(scr.index, full)
        check_window_unmoved(win, find_window(pids))
        try:
            crop_and_verify(full, win, scr, tmp)
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture the Lux window (macOS).")
    ap.add_argument("out", nargs="?", default=os.environ.get("SCREENSHOT_OUT"))
    ap.add_argument("--out", dest="out_flag")
    ap.add_argument("--interval", type=float, default=0.0, help="seconds apart")
    ap.add_argument("--count", type=int, default=1, help="number of captures")
    ap.add_argument("--no-raise", action="store_true", help="keep window order")
    a = ap.parse_args()
    out = Path(a.out_flag or a.out or ".tmp/lux-screenshot.png")
    try:
        if a.count <= 1:
            print(capture(out, raise_first=not a.no_raise))
            return 0
        for i in range(1, a.count + 1):
            t0 = time.monotonic()
            path = out.with_name(f"{out.stem}-{i:04d}{out.suffix or '.png'}")
            first = i == 1 and not a.no_raise
            print(capture(path, raise_first=first), flush=True)
            if i < a.count:
                time.sleep(max(0.0, a.interval - (time.monotonic() - t0)))
    except ScreenshotError as e:
        print(f"screenshot_macos.py: error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
