"""Snapshot portion of the pyghostty boundary; no socket or daemon policy.

Native allocations belong here, are copied into Python bytes, and are freed
with the allocator that produced them. The snapshot decoder transfers terminal
ownership to the Python wrapper, whose finalizer frees it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.terminal.ffi import Terminal, ffi, handle, init_sized, lib

if TYPE_CHECKING:
    from pyghostty._ffi import GhosttySelectionPointer, Pointer

CONTINUATION_LIMIT = 64 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


class SnapshotError(RuntimeError):
    """A snapshot operation failed or exceeded its resource limit."""


class ContinuationExhaustedError(SnapshotError):
    """No binary cut exists: the parser is mid-sequence beyond what is tracked."""


class NativeSnapshotCodec:
    """Native snapshot codec with explicit allocation and terminal ownership."""

    @staticmethod
    def tracked_terminal(cols: int = 80, rows: int = 24) -> Terminal:
        """Create a terminal that retains unfinished sequences for snapshots.

        Tracking must be enabled before feeding any output. Untracked terminals
        cannot encode a snapshot while their parser is inside an escape sequence.
        """
        term = Terminal(cols=cols, rows=rows, scrollback=10_000)
        limit = ffi.new("size_t*", CONTINUATION_LIMIT)
        result = lib.ghostty_terminal_set(
            handle(term), lib.GHOSTTY_TERMINAL_OPT_CONTINUATION_MAX_BYTES, limit
        )
        NativeSnapshotCodec._check(result, "enable continuation tracking")
        return term

    @staticmethod
    def encode_binary(term: Terminal) -> bytes:
        """Encode both screens, scrollback and tracked parser continuation."""
        out = ffi.new("uint8_t**")
        size = ffi.new("size_t*")
        NativeSnapshotCodec._check(
            lib.ghostty_snapshot_encode_alloc(handle(term), ffi.NULL, out, size),
            "snapshot encode (continuation tracking required outside ground state)",
            ContinuationExhaustedError,
        )
        return NativeSnapshotCodec._copy_and_free(out[0], size[0])

    @staticmethod
    def restore_binary(data: bytes) -> Terminal:
        """Restore a terminal and transfer ownership out of the decoder."""
        if not data or len(data) > MAX_SNAPSHOT_BYTES:
            raise SnapshotError("snapshot size is outside the supported bounds")
        decoder = ffi.new("GhosttySnapshotDecoder*")
        NativeSnapshotCodec._check(
            lib.ghostty_snapshot_decoder_new_buf(
                ffi.NULL, decoder, ffi.from_buffer(data), len(data)
            ),
            "snapshot decoder creation",
        )
        raw = ffi.new("GhosttyTerminal*")
        try:
            NativeSnapshotCodec._check(
                lib.ghostty_snapshot_decoder_decode(decoder[0], raw), "snapshot decode"
            )
        finally:
            lib.ghostty_snapshot_decoder_free(decoder[0])
        return Terminal.from_handle(raw)

    @staticmethod
    def active_screen_vt(term: Terminal) -> bytes:
        """Format exactly the active screen, including its cursor and input modes."""
        cols, rows = term.size
        opts = init_sized("GhosttyFormatterTerminalOptions")
        opts.emit = lib.GHOSTTY_FORMATTER_FORMAT_VT
        opts.extra.size = ffi.sizeof("GhosttyFormatterTerminalExtra")
        for name in (
            "palette",
            "modes",
            "scrolling_region",
            "tabstops",
            "pwd",
            "keyboard",
        ):
            setattr(opts.extra, name, True)
        opts.extra.screen.size = ffi.sizeof("GhosttyFormatterScreenExtra")
        for name in (
            "cursor",
            "style",
            "hyperlink",
            "protection",
            "kitty_keyboard",
            "charsets",
        ):
            setattr(opts.extra.screen, name, True)
        selection = NativeSnapshotCodec._selection(term, 0, cols - 1, rows - 1)
        opts.selection = selection
        formatter = ffi.new("GhosttyFormatter*")
        NativeSnapshotCodec._check(
            lib.ghostty_formatter_terminal_new(
                ffi.NULL, formatter, handle(term), opts[0]
            ),
            "formatter creation",
        )
        try:
            out = ffi.new("uint8_t**")
            size = ffi.new("size_t*")
            NativeSnapshotCodec._check(
                lib.ghostty_formatter_format_alloc(formatter[0], ffi.NULL, out, size),
                "formatter encode",
            )
            return NativeSnapshotCodec._copy_and_free(out[0], size[0])
        finally:
            lib.ghostty_formatter_free(formatter[0])

    @staticmethod
    def screen_rows(term: Terminal) -> list[str]:
        """Text rows without dropping empty rows; not a styled-cell comparison."""
        cols, rows = term.size
        return [
            NativeSnapshotCodec._plain_row(
                term, NativeSnapshotCodec._selection(term, y, cols - 1, y)
            )
            for y in range(rows)
        ]

    @staticmethod
    def _plain_row(term: Terminal, selection: GhosttySelectionPointer) -> str:
        opts = init_sized("GhosttyTerminalSelectionFormatOptions")
        opts.emit = lib.GHOSTTY_FORMATTER_FORMAT_PLAIN
        opts.unwrap, opts.trim, opts.selection = False, False, selection
        size = 4096
        while size <= MAX_SNAPSHOT_BYTES:
            buf = ffi.new("uint8_t[]", size)
            written = ffi.new("size_t*")
            result = lib.ghostty_terminal_selection_format_buf(
                handle(term), opts[0], buf, size, written
            )
            if result == 0:
                return (
                    bytes(ffi.buffer(buf, written[0]))
                    .decode("utf-8", "replace")
                    .rstrip("\n")
                )
            if result != lib.GHOSTTY_OUT_OF_SPACE:
                NativeSnapshotCodec._check(result, "row formatting")
            size *= 4
        raise SnapshotError("formatted row exceeds the supported size")

    @staticmethod
    def _selection(
        term: Terminal, y0: int, x1: int, y1: int
    ) -> GhosttySelectionPointer:
        sel = init_sized("GhosttySelection")
        sel.start, sel.end = term.ref(0, y0)[0], term.ref(x1, y1)[0]
        return sel

    @staticmethod
    def _copy_and_free(ptr: Pointer[int], size: int) -> bytes:
        try:
            if size > MAX_SNAPSHOT_BYTES:
                raise SnapshotError("encoded snapshot exceeds the supported size")
            return bytes(ffi.buffer(ptr, size))
        finally:
            lib.ghostty_free(ffi.NULL, ptr, size)

    @staticmethod
    def _check(
        result: int,
        operation: str,
        error: type[SnapshotError] = SnapshotError,
    ) -> None:
        if result:
            raise error(f"{operation} failed: Ghostty result {result}")


tracked_terminal = NativeSnapshotCodec.tracked_terminal
encode_binary = NativeSnapshotCodec.encode_binary
restore_binary = NativeSnapshotCodec.restore_binary
active_screen_vt = NativeSnapshotCodec.active_screen_vt
screen_rows = NativeSnapshotCodec.screen_rows
