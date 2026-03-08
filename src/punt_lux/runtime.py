"""Code execution runtime for render functions.

Compiles user-provided Python source, extracts a ``render(ctx)`` function,
and calls it each frame with a RenderContext.  Source is only executed after
the user grants consent via the ConsentDialog — this module trusts that the
consent gate has already been passed.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, cast


class RenderContext:
    """Per-frame context passed to user-defined render functions.

    Attributes are updated each frame by CodeExecutor before calling
    ``render(ctx)``.
    """

    __slots__ = ("_event_callback", "dt", "frame", "height", "state", "width")

    def __init__(
        self,
        *,
        state: dict[str, Any],
        dt: float,
        frame: int,
        width: float,
        height: float,
        event_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    ) -> None:
        self.state = state
        self.dt = dt
        self.frame = frame
        self.width = width
        self.height = height
        self._event_callback = event_callback

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

    def __init__(
        self,
        source: str,
        *,
        existing_state: dict[str, Any] | None = None,
        event_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    ) -> None:
        self.source = source
        self._render_fn: Callable[[RenderContext], None] | None = None
        self._state: dict[str, Any] = (
            existing_state if existing_state is not None else {}
        )
        self._frame: int = 0
        self._error: str | None = None
        self._error_tb: str | None = None
        self._event_callback = event_callback

        self._compile()

    def _compile(self) -> None:
        """Compile source and extract the render function."""
        try:
            code = compile(self.source, "<render_function>", "exec")
        except (SyntaxError, ValueError) as exc:
            self._error = f"SyntaxError: {exc}"
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

    def clear_error(self) -> None:
        """Clear the error state."""
        self._error = None
        self._error_tb = None

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
