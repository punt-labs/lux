"""Tests for the AST warning scanner."""

from __future__ import annotations

import pytest

from punt_lux.ast_check import check_source


class TestCleanSource:
    def test_arithmetic_is_clean(self) -> None:
        assert check_source("x = 1 + 2") == []

    def test_stdlib_safe_import_is_clean(self) -> None:
        assert check_source("import json") == []

    def test_function_def_is_clean(self) -> None:
        assert check_source("def foo():\n    return 42") == []


_SUSPICIOUS_MODULES = [
    "ctypes",
    "http",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "signal",
    "socket",
    "subprocess",
    "urllib",
]


class TestSuspiciousImports:
    @pytest.mark.parametrize("module", _SUSPICIOUS_MODULES)
    def test_import_flagged(self, module: str) -> None:
        warnings = check_source(f"import {module}")
        assert len(warnings) == 1
        assert module in warnings[0]

    @pytest.mark.parametrize("module", _SUSPICIOUS_MODULES)
    def test_from_import_flagged(self, module: str) -> None:
        warnings = check_source(f"from {module} import something")
        assert len(warnings) == 1
        assert module in warnings[0]

    def test_submodule_import_flagged(self) -> None:
        warnings = check_source("import os.path")
        assert len(warnings) == 1
        assert "os.path" in warnings[0]


# Builtin function names that the scanner should flag.
# These are string literals passed to check_source() for AST analysis —
# the scanner parses them, it does not run them.
_SUSPICIOUS_CALLS = [
    "__import__",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "locals",
    "open",
    "setattr",
]


class TestSuspiciousCalls:
    @pytest.mark.parametrize("call", _SUSPICIOUS_CALLS)
    def test_builtin_call_flagged(self, call: str) -> None:
        # String literal analyzed by AST scanner, never executed
        warnings = check_source(f"{call}('arg')")
        assert len(warnings) == 1
        assert call in warnings[0]


class TestSuspiciousAttributes:
    def test_subprocess_attr_flagged(self) -> None:
        warnings = check_source("subprocess.run(['ls'])")
        assert len(warnings) == 1
        assert "subprocess.run" in warnings[0]

    def test_sys_attr_flagged(self) -> None:
        warnings = check_source("sys.exit(1)")
        assert len(warnings) == 1
        assert "sys.exit" in warnings[0]


class TestSyntaxErrors:
    def test_syntax_error_returns_warning(self) -> None:
        warnings = check_source("def (broken")
        assert len(warnings) == 1
        assert "syntax" in warnings[0].lower()


class TestCombined:
    def test_multiple_warnings(self) -> None:
        source = "import subprocess\nopen('file.txt')"
        warnings = check_source(source)
        assert len(warnings) == 2
