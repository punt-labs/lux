"""The pyghostty boundary: every use of its private or C-level API lives here.

pyghostty 0.1.4 wraps only part of libghostty-vt in Python (``Terminal``).
The renderer needs much more — render state, raw cells, encoders,
selection — so it uses the generated C API (``ffi``/``lib``) directly, plus
two private helpers. That is why ``pyghostty`` is pinned exactly
(ADR-0002). Keeping those touches in one module means a pyghostty upgrade
is checked in one place.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Self

from pyghostty import (
    Terminal as NativeTerminal,
    __version__ as _pyghostty_version,
    ffi,
    lib,
)
from pyghostty._ffi import union_fn  # private: calls that pass a union by value
from pyghostty.core import init_sized  # sized-struct allocator

if TYPE_CHECKING:
    from pyghostty._ffi import GhosttySelectionPointer, GhosttyTerminalImpl, Pointer

__all__ = [
    "Terminal",
    "ffi",
    "handle",
    "init_sized",
    "lib",
    "scroll_viewport",
    "snapshot_version",
    "string_value",
    "terminal_title",
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


class Terminal(NativeTerminal):
    """Own the pinned binding's protected handle and finalizer conventions."""

    @property
    def native_handle(self) -> Pointer[GhosttyTerminalImpl]:
        return self._t[0]

    def formatted_selection(self, selection: GhosttySelectionPointer) -> str:
        return self._format_sel(selection, unwrap=True)

    @classmethod
    def from_handle(cls, raw: Pointer[Pointer[GhosttyTerminalImpl]]) -> Self:
        term = cls.__new__(cls)
        term._t = raw
        term._unknown_cb = term._reply_cb = term._cb_err = None
        term._free = weakref.finalize(term, lib.ghostty_terminal_free, raw[0])
        return term


class GhosttyAccess:
    """Adapter for handle access, viewport operations and library identity."""

    @staticmethod
    def handle(term: Terminal) -> Pointer[GhosttyTerminalImpl]:
        """Return the raw ``GhosttyTerminal`` handle behind a pyghostty Terminal."""
        return term.native_handle

    @staticmethod
    def scroll_viewport(term: Terminal, tag: int, delta: int = 0) -> None:
        """Move the viewport: ``GHOSTTY_SCROLL_VIEWPORT_{DELTA,BOTTOM,TOP,ROW}``."""
        value = ffi.new("LuxScrollViewport*")
        value.tag, value.delta = tag, delta
        _scroll_viewport(GhosttyAccess.handle(term), value[0])

    @staticmethod
    def string_value(term: Terminal, key: int) -> str:
        """Read a borrowed ``GhosttyString`` terminal datum (e.g. the title)."""
        buf = ffi.new("GhosttyString*")
        if (
            lib.ghostty_terminal_get(GhosttyAccess.handle(term), key, buf)
            or not buf.len
        ):
            return ""
        return str(ffi.buffer(buf.ptr, buf.len)[:].decode("utf-8", "replace"))

    @staticmethod
    def terminal_title(term: Terminal) -> str:
        """Read the title without exposing the native enum to callers."""
        return GhosttyAccess.string_value(term, lib.GHOSTTY_TERMINAL_DATA_TITLE)

    @staticmethod
    def snapshot_version() -> str:
        """The identity of the binary snapshot format this process can decode.

        Ghostty's binary snapshot is readable only by the same libghostty-vt, so
        two processes compare this before sending one. pyghostty is pinned
        exactly (ADR-0002) and bundles its own library, so its version names the
        library.
        """
        return f"pyghostty-{_pyghostty_version}"


handle = GhosttyAccess.handle
scroll_viewport = GhosttyAccess.scroll_viewport
string_value = GhosttyAccess.string_value
terminal_title = GhosttyAccess.terminal_title
snapshot_version = GhosttyAccess.snapshot_version
