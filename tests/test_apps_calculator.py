"""Tests for the Programmer Calculator applet."""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.apps.calculator import CALCULATOR_SOURCE, render_calculator
from punt_lux.ast_check import check_source
from punt_lux.runtime import CodeExecutor


class TestCalculatorSource:
    """Verify CALCULATOR_SOURCE compiles and passes AST checks."""

    def test_source_compiles(self) -> None:
        executor = CodeExecutor(CALCULATOR_SOURCE)
        assert not executor.has_error, executor.error_message

    def test_ast_check_clean(self) -> None:
        warnings = check_source(CALCULATOR_SOURCE)
        assert warnings == []


class TestRenderCalculator:
    """Verify render_calculator calls show_async with correct args."""

    def test_show_async_args(self) -> None:
        client = MagicMock()
        render_calculator(client)

        client.show_async.assert_called_once()
        args, kwargs = client.show_async.call_args
        assert args[0] == "app-calculator"  # scene_id
        assert kwargs["frame_id"] == "app-calculator"
        # elements is keyword arg
        elements = kwargs.get("elements", args[1] if len(args) > 1 else None)
        assert elements[0].source == CALCULATOR_SOURCE
