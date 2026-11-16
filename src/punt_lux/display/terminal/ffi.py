# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# pyright: reportOptionalSubscript=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""The pyghostty boundary: every use of its private or C-level API lives here.

pyghostty 0.1.4 wraps only part of libghostty-vt in Python (``Terminal``).
The renderer needs much more — render state, raw cells, encoders,
selection — so it uses the generated C API (``ffi``/``lib``) directly, plus
two private helpers. That is why ``pyghostty`` is pinned exactly
(ADR-0002). Keeping those touches in one module means a pyghostty upgrade
is checked in one place.
"""

from __future__ import annotations

from typing import Any

from pyghostty import Terminal, ffi, lib
from pyghostty._ffi import union_fn  # private: calls that pass a union by value
from pyghostty.core import init_sized  # sized-struct allocator

__all__ = [
    "Terminal",
    "ffi",
    "handle",
    "init_sized",
    "lib",
    "scroll_viewport",
    "string_value",
]

# ghostty_terminal_scroll_viewport takes a tagged union *by value*. cffi in ABI
# mode cannot pass unions by value, so declare a layout-identical struct twin
# and cast the symbol to a signature that uses it (same technique as
# pyghostty's own _ffi and tilix2).
ffi.cdef(
    "typedef struct { uint32_t tag; uint32_t _pad;"
    " int64_t delta; int64_t _pad2; } LuxScrollViewport;"
)
if ffi.sizeof("LuxScrollViewport") != ffi.sizeof("GhosttyTerminalScrollViewport"):
    msg = "LuxScrollViewport no longer matches GhosttyTerminalScrollViewport"
    raise ImportError(msg)
_scroll_viewport = union_fn(
    "ghostty_terminal_scroll_viewport",
    "GhosttyResult(*)(GhosttyTerminal, LuxScrollViewport)",
)


def handle(term: Terminal) -> Any:
    """Return the raw ``GhosttyTerminal`` handle behind a pyghostty Terminal."""
    return term._t[0]


def scroll_viewport(term: Terminal, tag: int, delta: int = 0) -> None:
    """Move the viewport: ``GHOSTTY_SCROLL_VIEWPORT_{DELTA,BOTTOM,TOP,ROW}``."""
    value = ffi.new("LuxScrollViewport*")
    value.tag, value.delta = tag, delta
    _scroll_viewport(handle(term), value[0])


def string_value(term: Terminal, key: int) -> str:
    """Read a borrowed ``GhosttyString`` terminal datum (e.g. the title)."""
    buf = ffi.new("GhosttyString*")
    if lib.ghostty_terminal_get(handle(term), key, buf) or not buf.len:
        return ""
    return str(ffi.buffer(buf.ptr, buf.len)[:].decode("utf-8", "replace"))
