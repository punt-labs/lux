"""The shared harness rejects failed imports, aliases and missing source trees."""

from __future__ import annotations

import pytest

from tests.fresh_imports import (
    assert_importable,
    assert_isolated,
    assert_not_importable,
    package_modules,
)


def test_source_modules_include_package_and_leaf() -> None:
    modules = package_modules("punt_lux.wire.stream")
    assert "punt_lux.wire.stream" in modules
    assert "punt_lux.wire.stream.frames" in modules
    assert not any(module.endswith(".__init__") for module in modules)


def test_empty_source_tree_is_not_silently_skipped() -> None:
    with pytest.raises(AssertionError, match="No Python modules found"):
        package_modules("punt_lux.no_such_import_test_package")


def test_importable_module_succeeds() -> None:
    assert_importable("sys")


def test_failed_import_reports_stderr() -> None:
    with pytest.raises(AssertionError, match="ModuleNotFoundError"):
        assert_importable("punt_lux.no_such_import_test_package")


def test_removed_module_succeeds() -> None:
    assert_not_importable("punt_lux.no_such_import_test_package")


def test_present_module_fails() -> None:
    with pytest.raises(AssertionError, match="Removed module still imports: sys"):
        assert_not_importable("sys")


def test_wrong_missing_module_is_not_accepted() -> None:
    with pytest.raises(AssertionError, match="ModuleNotFoundError"):
        assert_not_importable("punt_lux.no_such_import_test_package.nested")


def test_empty_isolation_policy_succeeds() -> None:
    assert_isolated("sys", ())


def test_isolation_reports_a_forbidden_module() -> None:
    with pytest.raises(AssertionError, match=r"Forbidden modules loaded:.*sys"):
        assert_isolated("sys", ("sys",))


def test_isolation_does_not_hide_import_failure() -> None:
    with pytest.raises(AssertionError, match="ModuleNotFoundError"):
        assert_isolated("punt_lux.no_such_import_test_package", ())
