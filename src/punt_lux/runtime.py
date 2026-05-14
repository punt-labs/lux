"""Code execution runtime for render functions.

Compiles user-provided Python source, extracts a ``render(ctx)`` function,
and calls it each frame with a RenderContext.  Source is only executed after
the user grants consent via the ConsentDialog — this module trusts that the
consent gate has already been passed.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, Self, cast


class RenderContext:
    """Per-frame context passed to user-defined render functions.

    A fresh instance is created each frame by CodeExecutor and passed to
    ``render(ctx)``.
    """

    __slots__ = ("_dt", "_event_callback", "_frame", "_height", "_state", "_width")

    _dt: float
    _event_callback: Callable[[str, dict[str, Any] | None], None] | None
    _frame: int
    _height: float
    _state: dict[str, Any]
    _width: float

    def __new__(
        cls,
        *,
        state: dict[str, Any],
        dt: float,
        frame: int,
        width: float,
        height: float,
        event_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._dt = dt
        self._frame = frame
        self._width = width
        self._height = height
        self._event_callback = event_callback
        return self

    @property
    def state(self) -> dict[str, Any]:
        """Persistent state dict shared across frames."""
        return self._state

    @state.setter
    def state(self, value: dict[str, Any]) -> None:
        self._state = value

    @property
    def dt(self) -> float:
        """Delta time since last frame."""
        return self._dt

    @dt.setter
    def dt(self, value: float) -> None:
        self._dt = value

    @property
    def frame(self) -> int:
        """Current frame number."""
        return self._frame

    @frame.setter
    def frame(self, value: int) -> None:
        self._frame = value

    @property
    def width(self) -> float:
        """Display width."""
        return self._width

    @width.setter
    def width(self, value: float) -> None:
        self._width = value

    @property
    def height(self) -> float:
        """Display height."""
        return self._height

    @height.setter
    def height(self, value: float) -> None:
        self._height = value

    def send(self, action: str, data: dict[str, Any] | None = None) -> None:
        """Send an event back to the agent."""
        if self._event_callback is not None:
            self._event_callback(action, data)


class CodeExecutor:
    """Compiles and executes a render function each frame.

    Usage::

        executor = CodeExecutor(source_code)
        # In your render loop:
        executor.render(dt, width, height)
        if executor.has_error:
            show_error(executor.error_message)
    """

    _source: str
    _render_fn: Callable[[RenderContext], None] | None
    _state: dict[str, Any]
    _frame: int
    _error: str | None
    _error_tb: str | None
    _event_callback: Callable[[str, dict[str, Any] | None], None] | None

    def __new__(
        cls,
        source: str,
        *,
        existing_state: dict[str, Any] | None = None,
        event_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._source = source
        self._render_fn = None
        self._state = existing_state if existing_state is not None else {}
        self._frame = 0
        self._error = None
        self._error_tb = None
        self._event_callback = event_callback

        self._compile()
        return self

    def _compile(self) -> None:
        """Compile source and extract the render function."""
        try:
            code = compile(self._source, "<render_function>", "exec")
        except (SyntaxError, ValueError) as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            self._error_tb = traceback.format_exc()
            return

        namespace: dict[str, Any] = {}
        try:
            exec(code, namespace)  # Gated by consent dialog
        except Exception as exc:  # Must catch anything user code throws
            self._error = f"Module-level error: {exc}"
            self._error_tb = traceback.format_exc()
            return

        if "render" not in namespace or not callable(namespace["render"]):
            self._error = "Source must define a callable `render(ctx)` function"
            return

        self._render_fn = cast("Callable[[RenderContext], None]", namespace["render"])

    @property
    def source(self) -> str:
        """The source code passed at construction."""
        return self._source

    @property
    def has_error(self) -> bool:
        """Whether the executor is in an error state.

        True when there is an explicit error message *or* when compilation
        failed to produce a render function.  This prevents ``clear_error()``
        from masking compile-time failures.
        """
        return self._error is not None or self._render_fn is None

    @property
    def error_message(self) -> str | None:
        """Human-readable error message, or None if no error."""
        return self._error

    @property
    def error_traceback(self) -> str | None:
        """Full traceback string, or None if no error."""
        return self._error_tb

    @property
    def state(self) -> dict[str, Any]:
        """Persistent state dict shared across frames."""
        return self._state

    _NO_RENDER_FN = "Source must define a callable `render(ctx)` function"

    def clear_error(self) -> None:
        """Clear the error state.

        If compilation failed to produce a render function, a fallback error
        message is kept so that ``has_error`` and ``error_message`` stay
        consistent.
        """
        self._error = None
        self._error_tb = None

        if self._render_fn is None:
            self._error = self._NO_RENDER_FN

    def render(self, dt: float, width: float, height: float) -> None:
        """Call the render function for one frame.

        If the executor has errored, this is a no-op.
        """
        if self._render_fn is None or self._error is not None:
            return

        ctx = RenderContext(
            state=self._state,
            dt=dt,
            frame=self._frame,
            width=width,
            height=height,
            event_callback=self._event_callback,
        )

        try:
            self._render_fn(ctx)
        except Exception as exc:  # Must catch anything user code throws
            self._error = f"Runtime error: {exc}"
            self._error_tb = traceback.format_exc()
            return

        self._frame += 1

    def hot_reload(self, new_source: str) -> CodeExecutor:
        """Create a new executor with new source, preserving state."""
        return CodeExecutor(
            new_source,
            existing_state=self._state,
            event_callback=self._event_callback,
        )
