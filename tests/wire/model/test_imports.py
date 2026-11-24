"""Every shared model module can initialize in its own interpreter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "packages/punt-lux-client/src"
_MODELS = _SRC / "punt_lux" / "wire" / "model"
_MODULES = [
    "punt_lux.wire",
    "punt_lux.kernel.connection_id",
    "punt_lux.kernel.programmer_error",
    *sorted(
        ".".join(path.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")
        for path in _MODELS.rglob("*.py")
    ),
]


@pytest.mark.parametrize("module", _MODULES)
def test_model_module_imports_in_fresh_process(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_facade_distinguishes_the_two_element_contracts() -> None:
    from punt_lux.wire.model import Element, ElementProtocol
    from punt_lux.wire.model.element import Element as StructuralElement
    from punt_lux.wire.model.elements import Element as WireElement

    assert Element is WireElement
    assert ElementProtocol is StructuralElement
