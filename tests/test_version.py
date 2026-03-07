"""Smoke test: package imports and version is set."""

from __future__ import annotations


def test_version_matches_metadata():
    from importlib.metadata import version

    from punt_lux import __version__

    assert __version__
    assert __version__ == version("punt-lux")


def test_package_imports():
    import punt_lux

    assert punt_lux.__all__ is not None
