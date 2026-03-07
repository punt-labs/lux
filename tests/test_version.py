"""Smoke test: package imports and version is set."""

from __future__ import annotations


def test_version_is_set():
    from punt_lux import __version__

    assert __version__ == "0.0.0"


def test_package_imports():
    import punt_lux

    assert punt_lux.__all__ is not None
