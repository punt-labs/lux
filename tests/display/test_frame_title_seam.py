"""Guard: only the title seam reads a frame's title to draw a title (DES-089).

A surface that reads the raw title shows neither the Hub rung nor the connection
rung, so two sessions' windows could read alike again. The window, the Windows
menu and the dock pill all take the seam's string; a new surface that reads the
attribute directly fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

_DISPLAY = Path(__file__).resolve().parents[2] / "src" / "punt_lux" / "display"

# The seam itself, the frame book that stores the title, and the introspection
# report that deliberately carries the base title beside the label.
_ALLOWED = frozenset({"replica/address_rendering.py", "replica/frame_book.py"})
_ALLOWED_REPORT = frozenset({"query_dispatcher.py"})
_RAW_TITLE = re.compile(r"\bheading\.title\b")


def test_no_display_module_but_the_seam_reads_the_raw_frame_title() -> None:
    offenders: list[str] = []
    scanned = 0
    for path in _DISPLAY.rglob("*.py"):
        scanned += 1
        rel = path.relative_to(_DISPLAY).as_posix()
        if rel in _ALLOWED or rel in _ALLOWED_REPORT:
            continue
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            if _RAW_TITLE.search(line):
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert scanned > 0, "guard scanned no files -- the source path is wrong"
    assert offenders == [], f"read the title through the seam: {offenders}"


def test_the_guard_would_catch_a_raw_read() -> None:
    assert _RAW_TITLE.search("label = frame.heading.title")
    assert _RAW_TITLE.search("size = calc(self._frame.heading.title)")
    assert not _RAW_TITLE.search("label = self._addressing.frame_title(frame)")
