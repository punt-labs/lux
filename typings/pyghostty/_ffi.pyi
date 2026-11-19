"""Used ABI declarations for the pinned pyghostty 0.1.4 library."""

from collections.abc import Buffer, Callable
from typing import Literal, overload

class CData: ...
class Null(CData): ...

class Pointer[T](CData):
    def __getitem__(self, index: int) -> T: ...
    def __setitem__(self, index: int, value: T) -> None: ...
    def __len__(self) -> int: ...

class ByteBuffer(Buffer):
    def __buffer__(self, flags: int) -> memoryview: ...
    def __getitem__(self, index: int | slice) -> bytes: ...

class GhosttyAllocator(CData):
    ctx: CData
    vtable: GhosttyAllocatorVtablePointer

class GhosttyAllocatorVtable(CData):
    alloc: Callable[[CData, int, int, int], CData]
    resize: Callable[[CData, CData, int, int, int, int], bool]
    remap: Callable[[CData, CData, int, int, int, int], CData]
    free: Callable[[CData, CData, int, int, int], None]

class GhosttyBuffer(CData):
    ptr: Pointer[int]
    cap: int
    len: int

class GhosttyCellsView(CData):
    ptr: Pointer[int]
    len: int

class GhosttyColorRgb(CData):
    r: int
    g: int
    b: int

class GhosttyFormatterImpl(CData): ...

class GhosttyFormatterScreenExtra(CData):
    size: int
    cursor: bool
    style: bool
    hyperlink: bool
    protection: bool
    kitty_keyboard: bool
    charsets: bool

class GhosttyFormatterTerminalExtra(CData):
    size: int
    palette: bool
    modes: bool
    scrolling_region: bool
    tabstops: bool
    pwd: bool
    keyboard: bool
    screen: GhosttyFormatterScreenExtra

class GhosttyFormatterTerminalOptions(CData):
    size: int
    emit: int
    unwrap: bool
    trim: bool
    extra: GhosttyFormatterTerminalExtra
    selection: GhosttySelectionPointer

class GhosttyGridRef(CData):
    size: int
    node: CData
    x: int
    y: int

class GhosttyKeyEncoderImpl(CData): ...
class GhosttyKeyEventImpl(CData): ...
class GhosttyMouseEncoderImpl(CData): ...

class GhosttyMouseEncoderSize(CData):
    size: int
    screen_width: int
    screen_height: int
    cell_width: int
    cell_height: int
    padding_top: int
    padding_bottom: int
    padding_right: int
    padding_left: int

class GhosttyMouseEventImpl(CData): ...

class GhosttyMousePosition(CData):
    x: float
    y: float

class GhosttyRenderStateColors(CData):
    size: int
    background: GhosttyColorRgb
    foreground: GhosttyColorRgb
    cursor: GhosttyColorRgb
    cursor_has_value: bool
    palette: GhosttyColorRgbPointer

class GhosttyRenderStateCursor(CData):
    size: int
    viewport_has_value: bool
    viewport_x: int
    viewport_y: int
    wide_tail: bool
    visible: bool
    blinking: bool
    password_input: bool
    visual_style: int

class GhosttyRenderStateImpl(CData): ...
class GhosttyRenderStateRowCellsImpl(CData): ...
class GhosttyRenderStateRowIteratorImpl(CData): ...

class GhosttyRenderStateRowSelection(CData):
    size: int
    start_x: int
    end_x: int

class GhosttySelection(CData):
    size: int
    start: GhosttyGridRef
    end: GhosttyGridRef
    rectangle: bool

class GhosttySnapshotDecoderImpl(CData): ...

class GhosttyString(CData):
    ptr: Pointer[int]
    len: int

class GhosttyStyle(CData):
    size: int
    fg_color: GhosttyStyleColor
    bg_color: GhosttyStyleColor
    underline_color: GhosttyStyleColor
    bold: bool
    italic: bool
    faint: bool
    blink: bool
    inverse: bool
    invisible: bool
    strikethrough: bool
    overline: bool
    underline: int

class GhosttyStyleColor(CData):
    tag: int
    value: GhosttyStyleColorValue

class GhosttyStyleColorValue(CData):
    palette: int
    rgb: GhosttyColorRgb
    _padding: int

class GhosttyTerminalImpl(CData): ...

class GhosttyTerminalScrollbar(CData):
    total: int
    offset: int
    len: int

class GhosttyTerminalSelectLineOptions(CData):
    size: int
    ref: GhosttyGridRef
    whitespace: Pointer[int]
    whitespace_len: int
    semantic_prompt_boundary: bool

class GhosttyTerminalSelectWordOptions(CData):
    size: int
    ref: GhosttyGridRef
    boundary_codepoints: Pointer[int]
    boundary_codepoints_len: int

class GhosttyTerminalSelectionFormatOptions(CData):
    size: int
    emit: int
    unwrap: bool
    trim: bool
    selection: GhosttySelectionPointer

class LuxScrollViewport(CData):
    tag: int
    _pad: int
    delta: int
    _pad2: int

class GhosttyAllocatorPointer(GhosttyAllocator, Pointer[GhosttyAllocator]): ...
class GhosttyAllocatorVtablePointer(
    GhosttyAllocatorVtable, Pointer[GhosttyAllocatorVtable]
): ...
class GhosttyBufferPointer(GhosttyBuffer, Pointer[GhosttyBuffer]): ...
class GhosttyCellsViewPointer(GhosttyCellsView, Pointer[GhosttyCellsView]): ...
class GhosttyGridRefPointer(GhosttyGridRef, Pointer[GhosttyGridRef]): ...
class GhosttyColorRgbPointer(GhosttyColorRgb, Pointer[GhosttyColorRgb]): ...
class GhosttyFormatterTerminalOptionsPointer(
    GhosttyFormatterTerminalOptions, Pointer[GhosttyFormatterTerminalOptions]
): ...
class GhosttyMouseEncoderSizePointer(
    GhosttyMouseEncoderSize, Pointer[GhosttyMouseEncoderSize]
): ...
class GhosttyMousePositionPointer(
    GhosttyMousePosition, Pointer[GhosttyMousePosition]
): ...
class GhosttyRenderStateColorsPointer(
    GhosttyRenderStateColors, Pointer[GhosttyRenderStateColors]
): ...
class GhosttyRenderStateCursorPointer(
    GhosttyRenderStateCursor, Pointer[GhosttyRenderStateCursor]
): ...
class GhosttyRenderStateRowSelectionPointer(
    GhosttyRenderStateRowSelection, Pointer[GhosttyRenderStateRowSelection]
): ...
class GhosttySelectionPointer(GhosttySelection, Pointer[GhosttySelection]): ...
class GhosttyStringPointer(GhosttyString, Pointer[GhosttyString]): ...
class GhosttyStylePointer(GhosttyStyle, Pointer[GhosttyStyle]): ...
class GhosttyTerminalScrollbarPointer(
    GhosttyTerminalScrollbar, Pointer[GhosttyTerminalScrollbar]
): ...
class GhosttyTerminalSelectLineOptionsPointer(
    GhosttyTerminalSelectLineOptions, Pointer[GhosttyTerminalSelectLineOptions]
): ...
class GhosttyTerminalSelectWordOptionsPointer(
    GhosttyTerminalSelectWordOptions, Pointer[GhosttyTerminalSelectWordOptions]
): ...
class GhosttyTerminalSelectionFormatOptionsPointer(
    GhosttyTerminalSelectionFormatOptions,
    Pointer[GhosttyTerminalSelectionFormatOptions],
): ...
class LuxScrollViewportPointer(LuxScrollViewport, Pointer[LuxScrollViewport]): ...

class Library:
    GHOSTTY_FORMATTER_FORMAT_PLAIN: int
    GHOSTTY_FORMATTER_FORMAT_VT: int
    GHOSTTY_KEY_A: int
    GHOSTTY_KEY_ACTION_PRESS: int
    GHOSTTY_KEY_ACTION_RELEASE: int
    GHOSTTY_KEY_ACTION_REPEAT: int
    GHOSTTY_KEY_ARROW_DOWN: int
    GHOSTTY_KEY_ARROW_UP: int
    GHOSTTY_KEY_UNIDENTIFIED: int
    GHOSTTY_MOUSE_ACTION_MOTION: int
    GHOSTTY_MOUSE_ACTION_PRESS: int
    GHOSTTY_MOUSE_ACTION_RELEASE: int
    GHOSTTY_MOUSE_BUTTON_FIVE: int
    GHOSTTY_MOUSE_BUTTON_FOUR: int
    GHOSTTY_MOUSE_BUTTON_LEFT: int
    GHOSTTY_MOUSE_BUTTON_MIDDLE: int
    GHOSTTY_MOUSE_BUTTON_RIGHT: int
    GHOSTTY_MOUSE_ENCODER_OPT_ANY_BUTTON_PRESSED: int
    GHOSTTY_MOUSE_ENCODER_OPT_SIZE: int
    GHOSTTY_OUT_OF_SPACE: int
    GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_BAR: int
    GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_BLOCK_HOLLOW: int
    GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_UNDERLINE: int
    GHOSTTY_RENDER_STATE_DATA_COLORS: int
    GHOSTTY_RENDER_STATE_DATA_CURSOR: int
    GHOSTTY_RENDER_STATE_DATA_DIRTY: int
    GHOSTTY_RENDER_STATE_DATA_ROW_ITERATOR: int
    GHOSTTY_RENDER_STATE_DIRTY_FULL: int
    GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_BG_COLOR: int
    GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_FG_COLOR: int
    GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_GRAPHEMES_UTF8: int
    GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_STYLE: int
    GHOSTTY_RENDER_STATE_ROW_DATA_CELLS: int
    GHOSTTY_RENDER_STATE_ROW_DATA_CELLS_RAW: int
    GHOSTTY_RENDER_STATE_ROW_DATA_DIRTY: int
    GHOSTTY_RENDER_STATE_ROW_DATA_SELECTION: int
    GHOSTTY_SCROLL_VIEWPORT_BOTTOM: int
    GHOSTTY_SCROLL_VIEWPORT_DELTA: int
    GHOSTTY_TERMINAL_DATA_ACTIVE_SCREEN: int
    GHOSTTY_TERMINAL_DATA_COLOR_PALETTE: int
    GHOSTTY_TERMINAL_DATA_SCROLLBAR: int
    GHOSTTY_TERMINAL_DATA_SELECTION: int
    GHOSTTY_TERMINAL_DATA_TITLE: int
    GHOSTTY_TERMINAL_OPT_COLOR_PALETTE: int
    GHOSTTY_TERMINAL_OPT_CONTINUATION_MAX_BYTES: int
    GHOSTTY_TERMINAL_OPT_SELECTION: int
    GHOSTTY_TERMINAL_SCREEN_ALTERNATE: int
    def ghostty_formatter_format_alloc(
        self,
        arg0: Pointer[GhosttyFormatterImpl] | Null,
        arg1: GhosttyAllocatorPointer | Null,
        arg2: Pointer[Pointer[int]] | Null,
        arg3: Pointer[int] | Null,
    ) -> int: ...
    def ghostty_formatter_free(
        self, arg0: Pointer[GhosttyFormatterImpl] | Null
    ) -> None: ...
    def ghostty_formatter_terminal_new(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttyFormatterImpl]] | Null,
        arg2: Pointer[GhosttyTerminalImpl] | Null,
        arg3: GhosttyFormatterTerminalOptions,
    ) -> int: ...
    def ghostty_free(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[int] | Null | bytes,
        arg2: int,
    ) -> None: ...
    def ghostty_key_encoder_encode(
        self,
        arg0: Pointer[GhosttyKeyEncoderImpl] | Null,
        arg1: Pointer[GhosttyKeyEventImpl] | Null,
        arg2: Pointer[bytes] | Null | bytes,
        arg3: int,
        arg4: Pointer[int] | Null,
    ) -> int: ...
    def ghostty_key_encoder_free(
        self, arg0: Pointer[GhosttyKeyEncoderImpl] | Null
    ) -> None: ...
    def ghostty_key_encoder_new(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttyKeyEncoderImpl]] | Null,
    ) -> int: ...
    def ghostty_key_encoder_setopt_from_terminal(
        self,
        arg0: Pointer[GhosttyKeyEncoderImpl] | Null,
        arg1: Pointer[GhosttyTerminalImpl] | Null,
    ) -> None: ...
    def ghostty_key_event_free(
        self, arg0: Pointer[GhosttyKeyEventImpl] | Null
    ) -> None: ...
    def ghostty_key_event_new(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttyKeyEventImpl]] | Null,
    ) -> int: ...
    def ghostty_key_event_set_action(
        self, arg0: Pointer[GhosttyKeyEventImpl] | Null, arg1: int
    ) -> None: ...
    def ghostty_key_event_set_consumed_mods(
        self, arg0: Pointer[GhosttyKeyEventImpl] | Null, arg1: int
    ) -> None: ...
    def ghostty_key_event_set_key(
        self, arg0: Pointer[GhosttyKeyEventImpl] | Null, arg1: int
    ) -> None: ...
    def ghostty_key_event_set_mods(
        self, arg0: Pointer[GhosttyKeyEventImpl] | Null, arg1: int
    ) -> None: ...
    def ghostty_key_event_set_unshifted_codepoint(
        self, arg0: Pointer[GhosttyKeyEventImpl] | Null, arg1: int
    ) -> None: ...
    def ghostty_key_event_set_utf8(
        self,
        arg0: Pointer[GhosttyKeyEventImpl] | Null,
        arg1: Pointer[bytes] | Null | bytes,
        arg2: int,
    ) -> None: ...
    def ghostty_mouse_encoder_encode(
        self,
        arg0: Pointer[GhosttyMouseEncoderImpl] | Null,
        arg1: Pointer[GhosttyMouseEventImpl] | Null,
        arg2: Pointer[bytes] | Null | bytes,
        arg3: int,
        arg4: Pointer[int] | Null,
    ) -> int: ...
    def ghostty_mouse_encoder_free(
        self, arg0: Pointer[GhosttyMouseEncoderImpl] | Null
    ) -> None: ...
    def ghostty_mouse_encoder_new(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttyMouseEncoderImpl]] | Null,
    ) -> int: ...
    def ghostty_mouse_encoder_setopt(
        self, arg0: Pointer[GhosttyMouseEncoderImpl] | Null, arg1: int, arg2: CData
    ) -> None: ...
    def ghostty_mouse_encoder_setopt_from_terminal(
        self,
        arg0: Pointer[GhosttyMouseEncoderImpl] | Null,
        arg1: Pointer[GhosttyTerminalImpl] | Null,
    ) -> None: ...
    def ghostty_mouse_event_free(
        self, arg0: Pointer[GhosttyMouseEventImpl] | Null
    ) -> None: ...
    def ghostty_mouse_event_new(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttyMouseEventImpl]] | Null,
    ) -> int: ...
    def ghostty_mouse_event_set_action(
        self, arg0: Pointer[GhosttyMouseEventImpl] | Null, arg1: int
    ) -> None: ...
    def ghostty_mouse_event_set_button(
        self, arg0: Pointer[GhosttyMouseEventImpl] | Null, arg1: int
    ) -> None: ...
    def ghostty_mouse_event_set_mods(
        self, arg0: Pointer[GhosttyMouseEventImpl] | Null, arg1: int
    ) -> None: ...
    def ghostty_mouse_event_set_position(
        self, arg0: Pointer[GhosttyMouseEventImpl] | Null, arg1: GhosttyMousePosition
    ) -> None: ...
    def ghostty_paste_encode(
        self,
        arg0: Pointer[bytes] | Null | bytes,
        arg1: int,
        arg2: bool,
        arg3: Pointer[bytes] | Null | bytes,
        arg4: int,
        arg5: Pointer[int] | Null,
    ) -> int: ...
    def ghostty_render_state_clean(
        self, arg0: Pointer[GhosttyRenderStateImpl] | Null
    ) -> int: ...
    def ghostty_render_state_free(
        self, arg0: Pointer[GhosttyRenderStateImpl] | Null
    ) -> None: ...
    def ghostty_render_state_get(
        self, arg0: Pointer[GhosttyRenderStateImpl] | Null, arg1: int, arg2: CData
    ) -> int: ...
    def ghostty_render_state_new(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttyRenderStateImpl]] | Null,
    ) -> int: ...
    def ghostty_render_state_row_cells_free(
        self, arg0: Pointer[GhosttyRenderStateRowCellsImpl] | Null
    ) -> None: ...
    def ghostty_render_state_row_cells_get(
        self,
        arg0: Pointer[GhosttyRenderStateRowCellsImpl] | Null,
        arg1: int,
        arg2: CData,
    ) -> int: ...
    def ghostty_render_state_row_cells_new(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttyRenderStateRowCellsImpl]] | Null,
    ) -> int: ...
    def ghostty_render_state_row_cells_select(
        self, arg0: Pointer[GhosttyRenderStateRowCellsImpl] | Null, arg1: int
    ) -> int: ...
    def ghostty_render_state_row_get(
        self,
        arg0: Pointer[GhosttyRenderStateRowIteratorImpl] | Null,
        arg1: int,
        arg2: CData,
    ) -> int: ...
    def ghostty_render_state_row_iterator_free(
        self, arg0: Pointer[GhosttyRenderStateRowIteratorImpl] | Null
    ) -> None: ...
    def ghostty_render_state_row_iterator_new(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttyRenderStateRowIteratorImpl]] | Null,
    ) -> int: ...
    def ghostty_render_state_row_iterator_next(
        self, arg0: Pointer[GhosttyRenderStateRowIteratorImpl] | Null
    ) -> bool: ...
    def ghostty_render_state_update(
        self,
        arg0: Pointer[GhosttyRenderStateImpl] | Null,
        arg1: Pointer[GhosttyTerminalImpl] | Null,
    ) -> int: ...
    def ghostty_snapshot_decoder_decode(
        self,
        arg0: Pointer[GhosttySnapshotDecoderImpl] | Null,
        arg1: Pointer[Pointer[GhosttyTerminalImpl]] | Null,
    ) -> int: ...
    def ghostty_snapshot_decoder_free(
        self, arg0: Pointer[GhosttySnapshotDecoderImpl] | Null
    ) -> None: ...
    def ghostty_snapshot_decoder_new_buf(
        self,
        arg0: GhosttyAllocatorPointer | Null,
        arg1: Pointer[Pointer[GhosttySnapshotDecoderImpl]] | Null,
        arg2: Pointer[int] | Null | bytes,
        arg3: int,
    ) -> int: ...
    def ghostty_snapshot_encode_alloc(
        self,
        arg0: Pointer[GhosttyTerminalImpl] | Null,
        arg1: GhosttyAllocatorPointer | Null,
        arg2: Pointer[Pointer[int]] | Null,
        arg3: Pointer[int] | Null,
    ) -> int: ...
    def ghostty_terminal_free(
        self, arg0: Pointer[GhosttyTerminalImpl] | Null
    ) -> None: ...
    def ghostty_terminal_get(
        self, arg0: Pointer[GhosttyTerminalImpl] | Null, arg1: int, arg2: CData
    ) -> int: ...
    def ghostty_terminal_select_line(
        self,
        arg0: Pointer[GhosttyTerminalImpl] | Null,
        arg1: GhosttyTerminalSelectLineOptionsPointer | Null,
        arg2: GhosttySelectionPointer | Null,
    ) -> int: ...
    def ghostty_terminal_select_word(
        self,
        arg0: Pointer[GhosttyTerminalImpl] | Null,
        arg1: GhosttyTerminalSelectWordOptionsPointer | Null,
        arg2: GhosttySelectionPointer | Null,
    ) -> int: ...
    def ghostty_terminal_selection_format_buf(
        self,
        arg0: Pointer[GhosttyTerminalImpl] | Null,
        arg1: GhosttyTerminalSelectionFormatOptions,
        arg2: Pointer[int] | Null | bytes,
        arg3: int,
        arg4: Pointer[int] | Null,
    ) -> int: ...
    def ghostty_terminal_set(
        self, arg0: Pointer[GhosttyTerminalImpl] | Null, arg1: int, arg2: CData
    ) -> int: ...
    def ghostty_type_json(self) -> Pointer[bytes]: ...

class FFI:
    NULL: Null
    @overload
    def new(
        self,
        declaration: Literal["GhosttyBuffer*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> GhosttyBufferPointer: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyCellsView*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> GhosttyCellsViewPointer: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyColorRgb*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> GhosttyColorRgbPointer: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyColorRgb[256]"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> GhosttyColorRgbPointer: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyFormatter*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyFormatterImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyKeyEncoder*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyKeyEncoderImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyKeyEvent*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyKeyEventImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyMouseEncoder*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyMouseEncoderImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyMouseEvent*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyMouseEventImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyMousePosition*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> GhosttyMousePositionPointer: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyRenderState*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyRenderStateImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyRenderStateDirty*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[int]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyRenderStateRowCells*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyRenderStateRowCellsImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyRenderStateRowIterator*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyRenderStateRowIteratorImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttySnapshotDecoder*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttySnapshotDecoderImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyString*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> GhosttyStringPointer: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyTerminal*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[GhosttyTerminalImpl]]: ...
    @overload
    def new(
        self,
        declaration: Literal["GhosttyTerminalScrollbar*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> GhosttyTerminalScrollbarPointer: ...
    @overload
    def new(
        self,
        declaration: Literal["LuxScrollViewport*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> LuxScrollViewportPointer: ...
    @overload
    def new(
        self,
        declaration: Literal["bool*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[bool]: ...
    @overload
    def new(
        self,
        declaration: Literal["char[]"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[bytes]: ...
    @overload
    def new(
        self,
        declaration: Literal["int*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[int]: ...
    @overload
    def new(
        self,
        declaration: Literal["size_t*"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[int]: ...
    @overload
    def new(
        self,
        declaration: Literal["uint8_t**"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[Pointer[int]]: ...
    @overload
    def new(
        self,
        declaration: Literal["uint8_t[]"],
        initializer: int | bytes | dict[str, int] | None = ...,
    ) -> Pointer[int]: ...
    def cdef(self, declaration: str) -> None: ...
    def sizeof(self, declaration: str) -> int: ...
    def buffer(self, pointer: CData, size: int = ...) -> ByteBuffer: ...
    def from_buffer(self, data: bytes) -> Pointer[int]: ...
    def string(self, pointer: CData) -> bytes: ...

ffi: FFI
lib: Library

def union_fn(name: str, signature: str) -> Callable[[CData, CData], int]: ...
