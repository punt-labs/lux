"""Regression: spinner/markdown renderers fall back when submodules are missing.

The original ``_render_spinner`` / ``_render_markdown`` lazily imported
``imspinner`` / ``imgui_md`` with ``try/except ImportError`` and degraded
gracefully when the optional submodules were absent.  When the per-kind
renderer classes split out, top-level imports replaced the lazy ones —
a missing submodule then cascaded through ``element_renderer.py`` and
crashed ``server.py`` at startup.

These tests assert the fallback restoration:

1. Importing the renderer module with the submodule absent does not raise.
2. The module-level submodule binding is ``None`` in that case (which the
   ``render`` method short-circuits on).
"""

from __future__ import annotations

import builtins
import importlib
import sys
from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture
def block_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[set[str]]:
    """Patch ``__import__`` to raise ImportError for the named modules.

    Yields the mutable name set; the test populates it before triggering
    the reload.  Restored automatically on fixture teardown.
    """
    blocked: set[str] = set()
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        # `from imgui_bundle import imspinner` shows up as
        # __import__("imgui_bundle", fromlist=("imspinner",)) — the submodule
        # name appears only in fromlist.  Block on either form.
        fromlist = kwargs.get("fromlist") or (args[2] if len(args) >= 3 else ())
        if name in blocked or any(item in blocked for item in fromlist):
            raise ImportError(f"blocked by test: {name} fromlist={fromlist!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    yield blocked


def _reimport(module_name: str) -> Any:
    """Drop the module from sys.modules and import it fresh."""
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_spinner_renderer_imports_when_imspinner_missing(
    block_module: set[str],
) -> None:
    block_module.add("imspinner")
    mod = _reimport("punt_lux.display.renderers.spinner_renderer")
    assert mod._imspinner is None, (
        "module-level imspinner binding must be None when the submodule is "
        "absent so SpinnerRenderer.render takes the text fallback"
    )


def test_markdown_renderer_imports_when_imgui_md_missing(
    block_module: set[str],
) -> None:
    block_module.add("imgui_md")
    mod = _reimport("punt_lux.display.renderers.markdown_renderer")
    assert mod._imgui_md is None, (
        "module-level imgui_md binding must be None when the submodule is "
        "absent so MarkdownRenderer.render takes the text fallback"
    )


def test_spinner_module_reload_restores_real_binding() -> None:
    """After the blocked-import test, a fresh import sees the real submodule.

    Skipped on environments where ``imspinner`` is legitimately absent — that
    is the graceful-degradation contract under test in the sibling cases.
    """
    pytest.importorskip("imgui_bundle.imspinner")
    mod = _reimport("punt_lux.display.renderers.spinner_renderer")
    assert mod._imspinner is not None


def test_markdown_module_reload_restores_real_binding() -> None:
    """After the blocked-import test, a fresh import sees the real submodule.

    Skipped on environments where ``imgui_md`` is legitimately absent — that
    is the graceful-degradation contract under test in the sibling cases.
    """
    pytest.importorskip("imgui_bundle.imgui_md")
    mod = _reimport("punt_lux.display.renderers.markdown_renderer")
    assert mod._imgui_md is not None
