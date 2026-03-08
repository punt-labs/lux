"""Tests for the code execution runtime."""

from __future__ import annotations

from typing import Any

from punt_lux.runtime import CodeExecutor, RenderContext


class TestRenderContext:
    def test_attributes_set(self) -> None:
        ctx = RenderContext(
            state={"x": 1},
            dt=0.016,
            frame=5,
            width=800.0,
            height=600.0,
        )
        assert ctx.state == {"x": 1}
        assert ctx.dt == 0.016
        assert ctx.frame == 5
        assert ctx.width == 800.0
        assert ctx.height == 600.0

    def test_send_with_callback(self) -> None:
        received: list[tuple[str, dict[str, Any] | None]] = []
        ctx = RenderContext(
            state={},
            dt=0.0,
            frame=0,
            width=0.0,
            height=0.0,
            event_callback=lambda a, d: received.append((a, d)),
        )
        ctx.send("click", {"x": 10})
        assert received == [("click", {"x": 10})]

    def test_send_without_callback(self) -> None:
        ctx = RenderContext(state={}, dt=0.0, frame=0, width=0.0, height=0.0)
        ctx.send("noop")  # Should not raise

    def test_uses_slots(self) -> None:
        ctx = RenderContext(state={}, dt=0.0, frame=0, width=0.0, height=0.0)
        assert not hasattr(ctx, "__dict__")


class TestCodeExecutorConstruction:
    def test_valid_source(self) -> None:
        executor = CodeExecutor("def render(ctx): pass")
        assert not executor.has_error
        assert executor.error_message is None
        assert executor.error_traceback is None

    def test_syntax_error(self) -> None:
        executor = CodeExecutor("def (broken")
        assert executor.has_error
        assert executor.error_message is not None
        assert "SyntaxError" in executor.error_message

    def test_null_byte_error(self) -> None:
        executor = CodeExecutor("x = 1\x00")
        assert executor.has_error
        assert executor.error_message is not None
        assert (
            "SyntaxError" in executor.error_message
            or "ValueError" in executor.error_message
        )

    def test_module_level_error(self) -> None:
        executor = CodeExecutor("raise ValueError('boom')")
        assert executor.has_error
        assert executor.error_message is not None
        assert "Module-level error" in executor.error_message
        assert executor.error_traceback is not None

    def test_missing_render_function(self) -> None:
        executor = CodeExecutor("x = 1")
        assert executor.has_error
        assert executor.error_message is not None
        assert "render(ctx)" in executor.error_message

    def test_render_not_callable(self) -> None:
        executor = CodeExecutor("render = 42")
        assert executor.has_error
        assert executor.error_message is not None
        assert "render(ctx)" in executor.error_message

    def test_source_stored(self) -> None:
        src = "def render(ctx): pass"
        executor = CodeExecutor(src)
        assert executor.source == src


class TestCodeExecutorRender:
    def test_frame_counter_increments(self) -> None:
        executor = CodeExecutor("def render(ctx): pass")
        executor.render(0.016, 800.0, 600.0)
        executor.render(0.016, 800.0, 600.0)
        assert executor._frame == 2

    def test_state_persists_across_frames(self) -> None:
        source = (
            "def render(ctx):\n"
            "    ctx.state.setdefault('n', 0)\n"
            "    ctx.state['n'] += 1"
        )
        executor = CodeExecutor(source)
        executor.render(0.016, 800.0, 600.0)
        executor.render(0.016, 800.0, 600.0)
        assert executor.state["n"] == 2

    def test_runtime_error_captured(self) -> None:
        source = "def render(ctx): raise RuntimeError('boom')"
        executor = CodeExecutor(source)
        executor.render(0.016, 800.0, 600.0)
        assert executor.has_error
        assert executor.error_message is not None
        assert "Runtime error" in executor.error_message
        assert "boom" in executor.error_message

    def test_noop_after_error(self) -> None:
        source = "def render(ctx): raise RuntimeError('boom')"
        executor = CodeExecutor(source)
        executor.render(0.016, 800.0, 600.0)
        executor.render(0.016, 800.0, 600.0)  # Should not raise
        assert executor._frame == 0

    def test_clear_error_after_runtime_error(self) -> None:
        source = "def render(ctx): raise RuntimeError('boom')"
        executor = CodeExecutor(source)
        executor.render(0.016, 800.0, 600.0)
        assert executor.has_error
        executor.clear_error()
        # Runtime error cleared — render fn still exists, so healthy
        assert not executor.has_error

    def test_clear_error_after_compile_error(self) -> None:
        executor = CodeExecutor("def (broken")
        assert executor.has_error
        executor.clear_error()
        # Compile error: _render_fn is None, so still in error state
        assert executor.has_error

    def test_event_callback_from_render(self) -> None:
        received: list[tuple[str, dict[str, Any] | None]] = []
        source = "def render(ctx): ctx.send('tick', {'f': ctx.frame})"
        executor = CodeExecutor(
            source,
            event_callback=lambda a, d: received.append((a, d)),
        )
        executor.render(0.016, 800.0, 600.0)
        assert received == [("tick", {"f": 0})]


class TestCodeExecutorExistingState:
    def test_preserves_existing_state(self) -> None:
        executor = CodeExecutor(
            "def render(ctx): pass",
            existing_state={"counter": 42},
        )
        assert executor.state["counter"] == 42

    def test_none_state_creates_empty(self) -> None:
        executor = CodeExecutor("def render(ctx): pass", existing_state=None)
        assert executor.state == {}


class TestHotReload:
    def test_preserves_state(self) -> None:
        src1 = "def render(ctx): ctx.state['v'] = 1"
        executor = CodeExecutor(src1)
        executor.render(0.016, 800.0, 600.0)

        src2 = "def render(ctx): ctx.state['v'] += 10"
        executor2 = executor.hot_reload(src2)
        executor2.render(0.016, 800.0, 600.0)
        assert executor2.state["v"] == 11

    def test_resets_frame_counter(self) -> None:
        executor = CodeExecutor("def render(ctx): pass")
        executor.render(0.016, 800.0, 600.0)
        executor.render(0.016, 800.0, 600.0)

        executor2 = executor.hot_reload("def render(ctx): pass")
        assert executor2._frame == 0

    def test_preserves_event_callback(self) -> None:
        received: list[tuple[str, dict[str, Any] | None]] = []
        executor = CodeExecutor(
            "def render(ctx): pass",
            event_callback=lambda a, d: received.append((a, d)),
        )
        executor2 = executor.hot_reload("def render(ctx): ctx.send('reloaded')")
        executor2.render(0.016, 800.0, 600.0)
        assert received == [("reloaded", None)]
